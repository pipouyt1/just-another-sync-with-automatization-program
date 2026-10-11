package app.hub.phone

import android.content.Context
import android.content.Intent
import android.os.BatteryManager
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.records.ActiveCaloriesBurnedRecord
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.request.ReadRecordsRequest
import androidx.health.connect.client.time.TimeRangeFilter
import java.time.Duration
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId

object Health {
    val PERMS = setOf(
        HealthPermission.getReadPermission(StepsRecord::class),
        HealthPermission.getReadPermission(DistanceRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getReadPermission(SleepSessionRecord::class),
        HealthPermission.getReadPermission(ActiveCaloriesBurnedRecord::class),
    )

    private var cache: Map<String, Double> = emptyMap()
    private var cacheAt = 0L

    fun available(c: Context) = HealthConnectClient.getSdkStatus(c) == HealthConnectClient.SDK_AVAILABLE

    fun battery(c: Context): Double? {
        val i = c.registerReceiver(null, android.content.IntentFilter(Intent.ACTION_BATTERY_CHANGED)) ?: return null
        val level = i.getIntExtra(BatteryManager.EXTRA_LEVEL, -1)
        val scale = i.getIntExtra(BatteryManager.EXTRA_SCALE, -1)
        return if (level < 0 || scale <= 0) null else level * 100.0 / scale
    }

    /** Lecturas de Health Connect de hoy. Como mucho una vez cada 2 minutos (salvo `force`); si falla, se queda lo anterior. */
    suspend fun read(c: Context, force: Boolean = false): Map<String, Double> {
        if (!force && System.currentTimeMillis() - cacheAt < 120_000) return cache
        if (!available(c)) {
            Status.health = "health connect no está disponible en este teléfono"
            return emptyMap()
        }
        val out = mutableMapOf<String, Double>()
        try {
            val client = HealthConnectClient.getOrCreate(c)
            val granted = client.permissionController.getGrantedPermissions()
            if (granted.isEmpty()) {
                Status.health = "sin permisos: pulsa «conectar health connect»"
                return emptyMap()
            }
            val now = Instant.now()
            val dayStart = LocalDate.now().atStartOfDay(ZoneId.systemDefault()).toInstant()
            val metrics = mutableSetOf<androidx.health.connect.client.aggregate.AggregateMetric<*>>()
            if (HealthPermission.getReadPermission(StepsRecord::class) in granted) metrics += StepsRecord.COUNT_TOTAL
            if (HealthPermission.getReadPermission(DistanceRecord::class) in granted) metrics += DistanceRecord.DISTANCE_TOTAL
            if (HealthPermission.getReadPermission(ActiveCaloriesBurnedRecord::class) in granted) metrics += ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL
            if (metrics.isNotEmpty()) {
                val r = client.aggregate(AggregateRequest(metrics, TimeRangeFilter.between(dayStart, now)))
                r[StepsRecord.COUNT_TOTAL]?.let { out["steps"] = it.toDouble() }
                r[DistanceRecord.DISTANCE_TOTAL]?.let { out["distance_km"] = Math.round(it.inKilometers * 100) / 100.0 }
                r[ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL]?.let { out["calories"] = Math.round(it.inKilocalories).toDouble() }
            }
            if (HealthPermission.getReadPermission(SleepSessionRecord::class) in granted) {
                val r = client.aggregate(AggregateRequest(setOf(SleepSessionRecord.SLEEP_DURATION_TOTAL),
                    TimeRangeFilter.between(now.minus(Duration.ofHours(24)), now)))
                r[SleepSessionRecord.SLEEP_DURATION_TOTAL]?.let { out["sleep_hours"] = Math.round(it.toMinutes() / 6.0) / 10.0 }
            }
            if (HealthPermission.getReadPermission(HeartRateRecord::class) in granted) {
                val recs = client.readRecords(ReadRecordsRequest(HeartRateRecord::class,
                    TimeRangeFilter.between(now.minus(Duration.ofHours(12)), now), ascendingOrder = false, pageSize = 5)).records
                recs.flatMap { it.samples }.maxByOrNull { it.time }?.let { out["heart_rate"] = it.beatsPerMinute.toDouble() }
            }
            Status.health = if (out.isEmpty()) "conectado, pero hoy no hay datos en health connect" else "ok"
            Status.healthAt = System.currentTimeMillis()
            cache = out
            cacheAt = System.currentTimeMillis()
        } catch (e: Exception) {
            // por ejemplo: leer en segundo plano puede estar restringido; se conserva lo último leído
            Status.health = "no se pudo leer (${e.javaClass.simpleName}); se reintenta al abrir la app"
            return cache
        }
        return out
    }
}
