package fi.puppycorp.puppybot

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.tooling.preview.Preview
import fi.puppycorp.puppybot.mdns.PuppybotMdns
import fi.puppycorp.puppybot.mdns.PuppybotDevice
import fi.puppycorp.puppybot.ui.theme.PuppybotTheme

class MainActivity : ComponentActivity() {
    private lateinit var mdns: PuppybotMdns

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        mdns = PuppybotMdns(this)
        setContent {
            PuppybotTheme {
                Scaffold(modifier = Modifier.fillMaxSize()) { innerPadding ->
                    PuppybotList(
                        modifier = Modifier.padding(innerPadding),
                        vm = mdns
                    )
                }
            }
        }
    }

    override fun onStart() {
        super.onStart()
        mdns.start()
    }

    override fun onStop() {
        super.onStop()
        mdns.stop()
    }
}

@Composable
private fun PuppybotList(modifier: Modifier = Modifier, vm: PuppybotMdns) {
    val devices: List<PuppybotDevice> by vm.devices.collectAsState(initial = emptyList())
    Column(modifier = modifier) {
        if (devices.isEmpty()) {
            Text("Searching for PuppyBots on _ws._tcp...", style = MaterialTheme.typography.bodyLarge)
        } else {
            Text("Found ${devices.size} PuppyBot(s):", style = MaterialTheme.typography.titleMedium)
            for (d in devices) {
                val host = d.host?.hostAddress ?: "?"
                val fw = d.attributes["fw"] ?: "?"
                Text("• ${d.name} @ $host:${d.port} (fw $fw)")
            }
        }
    }
}

@Preview(showBackground = true)
@Composable
private fun PuppybotListPreview() {
    PuppybotTheme {
        Column { Text("Preview") }
    }
}
