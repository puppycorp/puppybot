package fi.puppycorp.puppybot.mdns

import android.content.Context
import android.net.nsd.NsdManager
import android.net.nsd.NsdServiceInfo
import android.util.Log
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.channels.BufferOverflow
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.flow.SharedFlow
import kotlinx.coroutines.launch
import java.net.InetAddress

data class PuppybotDevice(
    val name: String,
    val host: InetAddress?,
    val port: Int,
    val attributes: Map<String, String> = emptyMap()
)

class PuppybotMdns(private val context: Context) {
    companion object {
        // mDNS service type advertised by the ESP32 firmware
        const val SERVICE_TYPE = "_ws._tcp."
        private const val TAG = "PuppybotMdns"
    }

    private val nsdManager: NsdManager =
        context.getSystemService(Context.NSD_SERVICE) as NsdManager

    private var discoveryListener: NsdManager.DiscoveryListener? = null
    private var resolveJobs = mutableMapOf<String, Job>()

    private val scope = CoroutineScope(Dispatchers.Main)

    private val _devices = MutableSharedFlow<List<PuppybotDevice>>(replay = 1, onBufferOverflow = BufferOverflow.DROP_OLDEST, extraBufferCapacity = 1)
    val devices: SharedFlow<List<PuppybotDevice>> = _devices

    private val current = linkedMapOf<String, PuppybotDevice>()

    fun start() {
        if (discoveryListener != null) return

        discoveryListener = object : NsdManager.DiscoveryListener {
            override fun onStartDiscoveryFailed(serviceType: String?, errorCode: Int) {
                Log.e(TAG, "NSD start failed: $errorCode for $serviceType")
                stop()
            }

            override fun onStopDiscoveryFailed(serviceType: String?, errorCode: Int) {
                Log.e(TAG, "NSD stop failed: $errorCode for $serviceType")
                stop()
            }

            override fun onDiscoveryStarted(serviceType: String?) {
                Log.i(TAG, "Discovery started for $serviceType")
            }

            override fun onDiscoveryStopped(serviceType: String?) {
                Log.i(TAG, "Discovery stopped for $serviceType")
            }

            override fun onServiceFound(serviceInfo: NsdServiceInfo) {
                // Expect service type: _ws._tcp.
                if (serviceInfo.serviceType != SERVICE_TYPE) return

                // Resolve each service to get host/port and TXT attributes
                val key = serviceInfo.serviceName + "@" + serviceInfo.serviceType

                // Avoid duplicate resolve
                if (resolveJobs.containsKey(key)) return

                val job = scope.launch {
                    try {
                        nsdManager.resolveService(serviceInfo, object : NsdManager.ResolveListener {
                            override fun onResolveFailed(serviceInfo: NsdServiceInfo?, errorCode: Int) {
                                Log.w(TAG, "Resolve failed: $errorCode for ${serviceInfo?.serviceName}")
                            }

                            override fun onServiceResolved(resolved: NsdServiceInfo) {
                                val name = resolved.serviceName
                                val host = resolved.host
                                val port = resolved.port
                                val attrs: Map<String, String> = try {
                                    // getAttributes() available API 21+, returns Map<String, ByteArray>
                                    val raw = resolved.attributes
                                    raw?.entries?.associate { it.key to String(it.value) } ?: emptyMap()
                                } catch (t: Throwable) {
                                    emptyMap()
                                }

                                // Filter likely PuppyBots: either name hints or TXT role=\"gateway\"
                                val looksLikePuppy =
                                    name.contains("puppy", ignoreCase = true) ||
                                    attrs["role"]?.equals("gateway", ignoreCase = true) == true

                                if (!looksLikePuppy) return

                                current[name] = PuppybotDevice(name, host, port, attrs)
                                emit()
                            }
                        })
                    } catch (t: Throwable) {
                        Log.e(TAG, "resolveService threw: ${t.message}", t)
                    } finally {
                        resolveJobs.remove(key)
                    }
                }
                resolveJobs[key] = job
            }

            override fun onServiceLost(serviceInfo: NsdServiceInfo) {
                val name = serviceInfo.serviceName
                if (current.remove(name) != null) emit()
            }
        }

        nsdManager.discoverServices(SERVICE_TYPE, NsdManager.PROTOCOL_DNS_SD, discoveryListener)
    }

    fun stop() {
        try {
            discoveryListener?.let { nsdManager.stopServiceDiscovery(it) }
        } catch (t: Throwable) {
            Log.w(TAG, "stopServiceDiscovery issue: ${t.message}")
        } finally {
            discoveryListener = null
        }

        // Cancel outstanding resolves
        resolveJobs.values.forEach { it.cancel() }
        resolveJobs.clear()
    }

    private fun emit() {
        scope.launch { _devices.emit(current.values.toList()) }
    }
}

