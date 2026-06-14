package com.apkhub.app

import android.annotation.SuppressLint
import android.app.DownloadManager
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.net.Uri
import android.os.Bundle
import android.view.KeyEvent
import android.webkit.DownloadListener
import android.webkit.URLUtil
import android.webkit.WebChromeClient
import android.webkit.WebResourceRequest
import android.webkit.WebSettings
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity

/**
 * A single-activity WebView shell that wraps the APKHub PWA (or any web URL).
 *
 * Features:
 *  • Full PWA support (JavaScript, DOM storage, IndexedDB, service workers)
 *  • Back-button navigates within the web app
 *  • APK download interception → DownloadManager → auto-opens the system installer
 *  • External links open in the browser; in-app links stay in the WebView
 *  • Survives rotation and process death (state save/restore)
 */
class MainActivity : AppCompatActivity() {

    private lateinit var webView: WebView
    private var downloadId: Long = -1L

    /** Fires when a DownloadManager download completes → offer to install APKs. */
    private val downloadCompleteReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            val id = intent.getLongExtra(DownloadManager.EXTRA_DOWNLOAD_ID, -1L)
            if (id == downloadId) {
                openDownloadedApk(id)
            }
        }
    }

    @SuppressLint("SetJavaScriptEnabled")
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        supportActionBar?.hide()

        webView = WebView(this).apply {
            layoutParams = FrameLayout.LayoutParams(
                FrameLayout.LayoutParams.MATCH_PARENT,
                FrameLayout.LayoutParams.MATCH_PARENT
            )
        }
        setContentView(webView)

        // ── Configure the WebView for a full PWA experience ──────────────
        webView.settings.apply {
            javaScriptEnabled = true
            domStorageEnabled = true          // localStorage — needed for favourites/offline
            databaseEnabled = true            // IndexedDB
            allowFileAccess = true
            allowContentAccess = true
            cacheMode = WebSettings.LOAD_DEFAULT
            loadWithOverviewMode = true
            useWideViewPort = true
            setSupportZoom(true)
            builtInZoomControls = true
            displayZoomControls = false
            mediaPlaybackRequiresUserGesture = false
            // Tag the UA so the PWA can detect it's inside the native shell
            userAgentString = userAgentString + " APKHubApp/" + BuildConfig.VERSION_NAME
        }

        // Keep GitHub-hosted content inside the app; send everything else to the browser.
        webView.webViewClient = object : WebViewClient() {
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                val host = request.url.host ?: return false
                val appHost = Uri.parse(BuildConfig.WEB_URL).host ?: return false
                // In-app: our own domain + GitHub (releases, avatars, assets)
                if (host == appHost ||
                    host.endsWith("github.com") ||
                    host.endsWith("githubusercontent.com") ||
                    host.endsWith("github.io")
                ) {
                    return false
                }
                // External link → system browser
                startActivity(Intent(Intent.ACTION_VIEW, request.url))
                return true
            }
        }

        webView.webChromeClient = WebChromeClient()

        // ── APK download interception ────────────────────────────────────
        // When the user taps "Download" in the web UI, the WebView fires a
        // download event. We route .apk files through DownloadManager and
        // automatically launch the installer when the download finishes.
        webView.setDownloadListener(DownloadListener { url, userAgent, contentDisposition, mimetype, _ ->
            val isApk = mimetype == "application/vnd.android.package-archive" ||
                         url.endsWith(".apk", ignoreCase = true)
            if (isApk) {
                downloadApk(url, userAgent, contentDisposition, mimetype)
            } else {
                // Non-APK file → hand to the system
                try {
                    startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
                } catch (_: Exception) {
                    Toast.makeText(this, "Cannot open this link", Toast.LENGTH_SHORT).show()
                }
            }
        })

        // ── Load ─────────────────────────────────────────────────────────
        if (savedInstanceState != null) {
            webView.restoreState(savedInstanceState)
        } else {
            webView.loadUrl(BuildConfig.WEB_URL)
        }

        // Listen for APK download completion
        registerReceiver(
            downloadCompleteReceiver,
            IntentFilter(DownloadManager.ACTION_DOWNLOAD_COMPLETE),
            Context.RECEIVER_NOT_EXPORTED
        )
    }

    /** Enqueue an APK download via the system DownloadManager. */
    @SuppressLint("Range")
    private fun downloadApk(url: String, userAgent: String, contentDisposition: String, mimetype: String) {
        try {
            val filename = URLUtil.guessFileName(url, contentDisposition, mimetype)
            val request = DownloadManager.Request(Uri.parse(url)).apply {
                setTitle(filename)
                setDescription("Downloading via ${BuildConfig.APP_NAME}")
                setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED)
                setDestinationInExternalFilesDir(this@MainActivity, null, filename)
                addRequestHeader("User-Agent", userAgent)
            }
            val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            downloadId = dm.enqueue(request)
            Toast.makeText(this, "Downloading $filename…", Toast.LENGTH_SHORT).show()
        } catch (e: Exception) {
            // Fallback: open in the browser which will handle the download
            try {
                startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
            } catch (_: Exception) {
                Toast.makeText(this, "Download failed", Toast.LENGTH_SHORT).show()
            }
        }
    }

    /** After an APK download finishes, query its URI and launch the installer. */
    @SuppressLint("Range")
    private fun openDownloadedApk(id: Long) {
        try {
            val dm = getSystemService(Context.DOWNLOAD_SERVICE) as DownloadManager
            val cursor = dm.query(DownloadManager.Query().setFilterById(id))
            if (cursor.moveToFirst()) {
                val localUri = cursor.getString(cursor.getColumnIndex(DownloadManager.COLUMN_LOCAL_URI))
                    ?: return
                val fileUri = Uri.parse(localUri)
                val install = Intent(Intent.ACTION_VIEW).apply {
                    setDataAndType(fileUri, "application/vnd.android.package-archive")
                    flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION
                }
                startActivity(install)
            }
            cursor.close()
        } catch (_: Exception) {
            // If the automatic open fails, the DownloadManager notification
            // still lets the user tap to install manually.
        }
    }

    // ── Lifecycle ─────────────────────────────────────────────────────────
    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        webView.saveState(outState)
    }

    override fun onDestroy() {
        try {
            unregisterReceiver(downloadCompleteReceiver)
        } catch (_: Exception) {
        }
        webView.destroy()
        super.onDestroy()
    }

    // ── Hardware back button navigates web history ────────────────────────
    @Deprecated("Deprecated in Java")
    override fun onKeyDown(keyCode: Int, event: KeyEvent?): Boolean {
        if (keyCode == KeyEvent.KEYCODE_BACK && webView.canGoBack()) {
            webView.goBack()
            return true
        }
        return super.onKeyDown(keyCode, event)
    }
}
