package com.ar.dalap

import android.content.ClipData
import android.content.ClipboardManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.provider.OpenableColumns
import android.util.Log
import androidx.activity.ComponentActivity
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedContent
import androidx.compose.animation.core.*
import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.interaction.MutableInteractionSource
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.*
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.drawBehind
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.ar.dalap.ui.theme.DaLAPTheme
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import kotlinx.coroutines.delay
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.Inet4Address
import java.net.NetworkInterface
import java.net.URL
import java.security.SecureRandom
import java.security.cert.X509Certificate
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.HttpsURLConnection
import javax.net.ssl.SSLContext
import javax.net.ssl.X509TrustManager

// ── Colour palette ────────────────────────────────────────────────────────────
private val BgDeep      = Color(0xFF060A16)
private val BgSurface   = Color(0xFF0B1020)
private val BgCard      = Color(0xFF0D1428)
private val BgCardAlt   = Color(0xFF0F172A)
private val Teal        = Color(0xFF38EDD6)
private val TealDim     = Color(0x1A38EDD6)
private val TealBorder  = Color(0x4038EDD6)
private val TealGlow    = Color(0x0838EDD6)
private val Green       = Color(0xFF34D48C)
private val GreenDim    = Color(0x1A34D48C)
private val GreenBorder = Color(0x4034D48C)
private val Amber       = Color(0xFFFFB347)
private val AmberDim    = Color(0x1AFFB347)
private val Red         = Color(0xFFFF6B6B)
private val RedDim      = Color(0x1AFF6B6B)
private val RedBorder   = Color(0x40FF6B6B)
private val Purple      = Color(0xFF9B8EFF)
private val PurpleDim   = Color(0x1A9B8EFF)
private val TextPrimary = Color(0xFFF0F6FF)
private val TextSecond  = Color(0xFFB8C5D6)
private val TextMuted   = Color(0xFF637489)
private val TextHint    = Color(0xFF3D4D5E)
private val Border      = Color(0x12FFFFFF)
private val BorderMid   = Color(0x1EFFFFFF)
private val BorderBright = Color(0x2CFFFFFF)

// ── Data models ───────────────────────────────────────────────────────────────
data class KbDocument(
	val id: Int,
	val originalName: String,
	val filename: String = "",
	val fileType: String,
	val subject: String,
	val uploadDate: String,
	val fileSize: Long,
	val chunkCount: Int = 0,
) {
	val displayName: String get() {
		val orig = originalName.takeIf { it.isNotEmpty() && it != "—" }
		val file = filename.takeIf { it.isNotEmpty() }
		return orig ?: file ?: "Tài liệu"
	}
}

// ── State ─────────────────────────────────────────────────────────────────────
object DalapServerState {
	@Volatile var running: Boolean = false
	@Volatile var docCount: Int    = 0
	@Volatile var chunkCount: Int  = 0
	@Volatile var apiKey: String   = ""
}

// ── Activity ──────────────────────────────────────────────────────────────────
class MainActivity : ComponentActivity() {

	private val serverStatus = mutableStateOf("Đang khởi động...")
	private val serverUrl    = mutableStateOf("")
	private val docCount     = mutableStateOf(0)
	private val chunkCount   = mutableStateOf(0)

	override fun onCreate(savedInstanceState: Bundle?) {
		super.onCreate(savedInstanceState)
		enableEdgeToEdge()
		startDalapServer()

		setContent {
			DaLAPTheme {
				DalapScreen(
					status     = serverStatus.value,
					url        = serverUrl.value,
					docCount   = docCount.value,
					chunkCount = chunkCount.value,
					onRefresh  = { refreshState() },
					onOpenAR   = { openBrowser(serverUrl.value) },
				)
			}
		}
	}

	private fun refreshState() {
		val ip       = getLocalIpv4Address()
		serverUrl.value = "https://$ip:5000"
		serverStatus.value = if (DalapServerState.running)
			"Server đang chạy" else "Server chưa chạy"

		lifecycleScope.launch {
			val counts = fetchServerCounts(serverUrl.value)
			if (counts != null) {
				DalapServerState.docCount = counts.first
				DalapServerState.chunkCount = counts.second
			}
			docCount.value = DalapServerState.docCount
			chunkCount.value = DalapServerState.chunkCount
		}
	}

	private fun openBrowser(url: String) {
		if (url.isBlank()) return
		try {
			startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
		} catch (e: Exception) {
			Log.e("DALAP", "Cannot open browser: ${e.message}")
		}
	}

	private fun startDalapServer() {
		val ip = getLocalIpv4Address()
		serverUrl.value = "https://$ip:5000"

		if (DalapServerState.running) {
			serverStatus.value = "Server đang chạy"
			return
		}

		serverStatus.value = "Đang khởi động..."

		Thread {
			try {
				if (!Python.isStarted()) Python.start(AndroidPlatform(this))
				val py = Python.getInstance()

				val dataDir = File(filesDir, "resfes_data").absolutePath
				val osModule = py.getModule("os")
				val env = osModule.get("environ")
				env?.callAttr("__setitem__", "RESFES_DATA_DIR", dataDir)
				env?.callAttr("__setitem__", "RESFES_KB_MODE", "local")

				val module = py.getModule("resfes")
				DalapServerState.apiKey = module.get("API_KEY")?.toString().orEmpty()

				DalapServerState.running = true
				runOnUiThread { serverStatus.value = "Server đang chạy" }

				try {
					val health = module.callAttr("get_health_info")
					DalapServerState.docCount = health["docs"]?.toInt() ?: 0
					DalapServerState.chunkCount = health["chunks"]?.toInt() ?: 0
					runOnUiThread {
						docCount.value   = DalapServerState.docCount
						chunkCount.value = DalapServerState.chunkCount
					}
				} catch (e: Exception) {
					Log.w("DALAP", "Could not fetch health info: ${e.message}")
				}

				module.callAttr("start_dalap_server")
			} catch (e: Exception) {
				Log.e("DALAP", "Server error: ${e.localizedMessage}", e)
				DalapServerState.running = false
				runOnUiThread {
					serverStatus.value = "Lỗi: ${e.localizedMessage?.take(60) ?: "unknown"}"
				}
			}
		}.start()
	}

	private fun getLocalIpv4Address(): String {
		return try {
			NetworkInterface.getNetworkInterfaces()?.toList().orEmpty()
				.filter { it.isUp && !it.isLoopback }
				.flatMap { it.inetAddresses.toList() }
				.filterIsInstance<Inet4Address>()
				.firstOrNull { !it.isLoopbackAddress }
				?.hostAddress ?: "localhost"
		} catch (_: Exception) { "localhost" }
	}
}

// ── Root app với bottom navigation ───────────────────────────────────────────
enum class AppTab { DASHBOARD, KNOWLEDGE_BASE }

@Composable
fun MainApp(
	status: String,
	url: String,
	docCount: Int,
	chunkCount: Int,
	onRefresh: () -> Unit,
	onOpenAR: () -> Unit,
) {
	var selectedTab by remember { mutableStateOf(AppTab.DASHBOARD) }
	var selectedKbDocIds by remember { mutableStateOf<Set<Int>>(emptySet()) }

	Scaffold(
		containerColor = BgDeep,
		contentWindowInsets = WindowInsets.statusBars,
		bottomBar = {
			BottomNavBar(
				selected = selectedTab,
				onSelect = { selectedTab = it },
			)
		}
	) { innerPadding ->
		Box(
			modifier = Modifier
				.fillMaxSize()
				.padding(innerPadding)
		) {
			when (selectedTab) {
				AppTab.DASHBOARD -> DashboardScreen(
					status     = status,
					url        = url,
					docCount   = docCount,
					chunkCount = chunkCount,
					onRefresh  = onRefresh,
					onOpenAR   = onOpenAR,
				)
				AppTab.KNOWLEDGE_BASE -> KnowledgeBaseScreen(
					serverUrl      = url,
					onRefreshStats = onRefresh,
					selectedDocIds = selectedKbDocIds,
					onSelectedDocIdsChange = { selectedKbDocIds = it },
				)
			}
		}
	}
}

// ── Bottom Nav Bar ────────────────────────────────────────────────────────────
@Composable
fun BottomNavBar(
	selected: AppTab,
	onSelect: (AppTab) -> Unit,
) {
	Surface(
		color = Color(0xFF080D1C),
		tonalElevation = 0.dp,
		shadowElevation = 0.dp,
	) {
		Row(
			modifier = Modifier
				.fillMaxWidth()
				.drawBehind {
					drawLine(
						color = Color(0x1AFFFFFF),
						start = Offset(0f, 0f),
						end = Offset(size.width, 0f),
						strokeWidth = 0.5.dp.toPx(),
					)
				}
				.navigationBarsPadding()
				.height(64.dp)
				.padding(horizontal = 24.dp),
			horizontalArrangement = Arrangement.SpaceEvenly,
			verticalAlignment = Alignment.CenterVertically,
		) {
			NavItem(
				label    = "Dashboard",
				icon     = Icons.Outlined.Dashboard,
				selected = selected == AppTab.DASHBOARD,
				onClick  = { onSelect(AppTab.DASHBOARD) },
			)
			NavItem(
				label    = "Knowledge Base",
				icon     = Icons.Outlined.MenuBook,
				selected = selected == AppTab.KNOWLEDGE_BASE,
				onClick  = { onSelect(AppTab.KNOWLEDGE_BASE) },
			)
		}
	}
}

