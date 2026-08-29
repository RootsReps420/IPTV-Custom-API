package com.iptvmonitor.player.data

import okhttp3.OkHttpClient
import java.security.SecureRandom
import java.security.cert.X509Certificate
import java.util.concurrent.TimeUnit
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

/** VLC UA — same family the monitor uses so panels that fingerprint clients still answer. */
const val STREAM_USER_AGENT = "VLC/3.0.20 LibVLC/3.0.20"

object HttpClients {
    @Volatile
    var userAgent: String = STREAM_USER_AGENT

    val trustAll: X509TrustManager = object : X509TrustManager {
        override fun checkClientTrusted(chain: Array<X509Certificate>, authType: String) = Unit
        override fun checkServerTrusted(chain: Array<X509Certificate>, authType: String) = Unit
        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()
    }

    val shared: OkHttpClient by lazy { baseBuilder(15, 90, 30, 120).build() }

    val epg: OkHttpClient by lazy {
        shared.newBuilder()
            .connectTimeout(20, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS)
            .writeTimeout(30, TimeUnit.SECONDS)
            .callTimeout(0, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
    }

    /** Login / M3U check only. Panels that dump the whole library on player_api.php must not sit here for minutes. */
    val probe: OkHttpClient by lazy {
        shared.newBuilder()
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(15, TimeUnit.SECONDS)
            .writeTimeout(10, TimeUnit.SECONDS)
            .callTimeout(25, TimeUnit.SECONDS)
            .build()
    }

    /**
     * Live/VOD bytes. Short connect so a dead channel fails in a few seconds;
     * no read/call timeout so a healthy live pipe is not killed mid-stream.
     */
    val stream: OkHttpClient by lazy {
        shared.newBuilder()
            .connectTimeout(8, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.SECONDS)
            .writeTimeout(15, TimeUnit.SECONDS)
            .callTimeout(0, TimeUnit.SECONDS)
            .retryOnConnectionFailure(true)
            .build()
    }

    private fun baseBuilder(
        connectSec: Long,
        readSec: Long,
        writeSec: Long,
        callSec: Long,
    ): OkHttpClient.Builder {
        val ssl = SSLContext.getInstance("TLS")
        ssl.init(null, arrayOf(trustAll), SecureRandom())
        return OkHttpClient.Builder()
            .sslSocketFactory(ssl.socketFactory, trustAll)
            .hostnameVerifier { _, _ -> true }
            .connectTimeout(connectSec, TimeUnit.SECONDS)
            .readTimeout(readSec, TimeUnit.SECONDS)
            .writeTimeout(writeSec, TimeUnit.SECONDS)
            .callTimeout(callSec, TimeUnit.SECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
            .addInterceptor { chain ->
                chain.proceed(
                    chain.request().newBuilder()
                        .header("User-Agent", userAgent.ifBlank { STREAM_USER_AGENT })
                        .header("Accept", "*/*")
                        .build(),
                )
            }
    }
}
