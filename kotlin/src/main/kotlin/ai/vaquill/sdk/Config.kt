package ai.vaquill.sdk

import java.time.Duration

/** Constants shared by the transport. Values mirror the Python SDK. */
public object Defaults {
    public const val BASE_URL: String = "https://api.vaquill.ai"
    public const val API_KEY_ENV: String = "VAQUILL_API_KEY"
    public const val BASE_URL_ENV: String = "VAQUILL_BASE_URL"
    public const val API_KEY_PREFIX: String = "vq_key_"
    public const val MAX_RETRIES: Int = 2

    /** Total time allowed for one HTTP attempt. [Duration.ZERO] disables it. */
    public val TIMEOUT: Duration = Duration.ofSeconds(60)

    /** Time allowed to open a connection. */
    public val CONNECT_TIMEOUT: Duration = Duration.ofSeconds(5)
}

internal const val INITIAL_RETRY_DELAY_SECONDS = 0.5
internal const val MAX_RETRY_DELAY_SECONDS = 8.0

/** A server-requested wait longer than this is not worth holding the caller for. */
internal const val MAX_RETRY_AFTER_SECONDS = 120.0
internal const val IDEMPOTENCY_HEADER = "Idempotency-Key"
internal const val REPLAYED_HEADER = "Idempotent-Replayed"
internal const val IDEMPOTENCY_STATUS_HEADER = "Idempotency-Status"
internal const val REQUEST_ID_HEADER = "X-Request-ID"

/** Package version, sent in the `User-Agent` header as `vaquill-kotlin/<version>`. */
public const val SDK_VERSION: String = "0.1.0"
