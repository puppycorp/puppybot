package com.puppybot.android

import android.content.Intent
import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import android.widget.Button

class MainActivity : AppCompatActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        findViewById<Button>(R.id.bluetoothBtn).setOnClickListener {
            startActivity(Intent(this, BluetoothActivity::class.java))
        }

        findViewById<Button>(R.id.connectServerBtn).setOnClickListener {
            startActivity(Intent(this, ServerClientActivity::class.java))
        }

        findViewById<Button>(R.id.hostServerBtn).setOnClickListener {
            startActivity(Intent(this, HostServerActivity::class.java))
        }
    }
}
