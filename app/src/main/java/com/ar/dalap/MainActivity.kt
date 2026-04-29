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

// Material Icons shim — using unicode symbols as fallback so we don't need extra dependency
private object Icons {
    object Outlined {
        const val Dashboard = "◧"
        const val MenuBook  = "◩"
    }
}

@Composable
fun NavItem(label: String, icon: String, selected: Boolean, onClick: () -> Unit) {
    val interactionSource = remember { MutableInteractionSource() }
    val scale by animateFloatAsState(
        targetValue = if (selected) 1f else 0.95f,
        animationSpec = spring(dampingRatio = Spring.DampingRatioMediumBouncy),
        label = "navScale"
    )

    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(16.dp))
            .clickable(
                interactionSource = interactionSource,
                indication = ripple(bounded = true, color = Teal),
                onClick = onClick,
            )
            .graphicsLayer { scaleX = scale; scaleY = scale }
            .size(48.dp),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            modifier = Modifier
                .size(40.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(if (selected) TealDim else Color.Transparent)
                .border(
                    width = if (selected) 1.dp else 0.dp,
                    color = if (selected) TealBorder else Color.Transparent,
                    shape = RoundedCornerShape(12.dp),
                ),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = icon,
                fontSize = 20.sp,
                color = if (selected) Teal else TextMuted,
            )
        }
    }
}

// ── Dashboard screen ──────────────────────────────────────────────────────────
@Composable
fun DashboardScreen(
    status: String,
    url: String,
    docCount: Int,
    chunkCount: Int,
    onRefresh: () -> Unit,
    onOpenAR: () -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp)
            .padding(top = 20.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        AppHeader()
        Spacer(Modifier.height(4.dp))
        ServerStatusCard(status = status)
        UrlCard(url = url)
        StatsRow(docCount = docCount, chunkCount = chunkCount)
        EndpointsCard()
        ActionButtons(onRefresh = onRefresh, onOpenAR = onOpenAR, url = url)
    }
}

// ── Knowledge Base screen ─────────────────────────────────────────────────────
@Composable
fun KnowledgeBaseScreen(
    serverUrl: String,
    onRefreshStats: () -> Unit,
    selectedDocIds: Set<Int>,
    onSelectedDocIdsChange: (Set<Int>) -> Unit,
) {
    val coroutineScope = rememberCoroutineScope()
    val context        = LocalContext.current

    var documents   by remember { mutableStateOf<List<KbDocument>>(emptyList()) }
    var totalDocs   by remember { mutableStateOf(0) }
    var totalChunks by remember { mutableStateOf(0) }
    var isLoading   by remember { mutableStateOf(false) }
    var isUploading by remember { mutableStateOf(false) }
    var uploadMsg   by remember { mutableStateOf("") }
    var processingStage by remember { mutableStateOf("") }
    var processingProgress by remember { mutableStateOf(0) }
    var showIngestWarning by remember { mutableStateOf(false) }
    var ingestWarningText by remember { mutableStateOf("") }
    var filterSubj  by remember { mutableStateOf("") }
    var searchQuery by remember { mutableStateOf("") }
    var deleteConfirmId by remember { mutableStateOf<Int?>(null) }
    var pendingUploadUri by remember { mutableStateOf<Uri?>(null) }
    var pendingUploadName by remember { mutableStateOf("") }
    var pendingDisplayName by remember { mutableStateOf("") }
    var pendingFileType by remember { mutableStateOf("txt") }

    val baseUrl = serverUrl.ifBlank { "https://localhost:5000" }

    fun loadDocs() {
        coroutineScope.launch {
            isLoading = true
            try {
                val docs = fetchDocuments(baseUrl, filterSubj.ifBlank { null })
                documents = docs
                val validIds = docs.mapTo(mutableSetOf()) { it.id }
                val cleanedSelection = selectedDocIds.intersect(validIds)
                if (cleanedSelection != selectedDocIds) {
                    onSelectedDocIdsChange(cleanedSelection)
                }
            } catch (e: Exception) {
                Log.e("KB", "Load error: ${e.message}")
            } finally {
                isLoading = false
            }
        }
    }

    fun loadHealth() {
        coroutineScope.launch {
            try {
                val counts = fetchServerCounts(baseUrl)
                if (counts != null) {
                    totalDocs = counts.first
                    totalChunks = counts.second
                }
            } catch (e: Exception) {
                Log.w("KB", "Health load error: ${e.message}")
            }
        }
    }

    LaunchedEffect(baseUrl) {
        loadDocs()
        loadHealth()
        onRefreshStats()
    }

    val fileLauncher = rememberLauncherForActivityResult(
        ActivityResultContracts.GetContent()
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        val name = resolveDisplayName(context, uri)
        val mimeType = context.contentResolver.getType(uri) ?: ""
        val fileType = when {
            mimeType.contains("pdf")  -> "pdf"
            mimeType.contains("text") -> "txt"
            else                      -> "txt"
        }
        pendingUploadUri = uri
        pendingUploadName = name
        pendingDisplayName = name
        pendingFileType = fileType
    }

    // Upload naming dialog
    if (pendingUploadUri != null) {
        AlertDialog(
            onDismissRequest = {
                if (!isUploading) {
                    pendingUploadUri = null
                    pendingUploadName = ""
                    pendingDisplayName = ""
                    pendingFileType = "txt"
                }
            },
            containerColor   = BgCard,
            shape            = RoundedCornerShape(20.dp),
            titleContentColor = TextPrimary,
            textContentColor  = TextSecond,
            title = {
                Column {
                    Text(
                        "Upload tài liệu",
                        fontWeight = FontWeight.Bold,
                        fontSize = 16.sp,
                        color = TextPrimary,
                    )
                    Spacer(Modifier.height(4.dp))
                    // Show pending file name
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Box(
                            modifier = Modifier
                                .clip(RoundedCornerShape(4.dp))
                                .background(TealDim)
                                .padding(horizontal = 6.dp, vertical = 2.dp)
                        ) {
                            Text(
                                pendingFileType.uppercase(),
                                fontSize = 10.sp,
                                fontWeight = FontWeight.Bold,
                                color = Teal,
                                letterSpacing = 0.5.sp,
                            )
                        }
                        Spacer(Modifier.width(6.dp))
                        Text(
                            pendingUploadName,
                            fontSize = 11.sp,
                            color = TextMuted,
                            maxLines = 1,
                            overflow = TextOverflow.Ellipsis,
                        )
                    }
                }
            },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(
                        "Đặt tên hiển thị cho tài liệu:",
                        fontSize = 12.sp,
                        color = TextMuted,
                    )
                    OutlinedTextField(
                        value = pendingDisplayName,
                        onValueChange = { pendingDisplayName = it },
                        placeholder = { Text("Tên tài liệu...", fontSize = 12.sp) },
                        singleLine = true,
                        textStyle = LocalTextStyle.current.copy(fontSize = 13.sp, color = TextPrimary),
                        colors = OutlinedTextFieldDefaults.colors(
                            focusedBorderColor      = Teal,
                            unfocusedBorderColor    = BorderMid,
                            cursorColor             = Teal,
                            focusedContainerColor   = BgDeep,
                            unfocusedContainerColor = BgDeep,
                        ),
                        shape = RoundedCornerShape(12.dp),
                    )
                }
            },
            confirmButton = {
                Button(
                    enabled = !isUploading,
                    onClick = {
                        val uploadUri   = pendingUploadUri ?: return@Button
                        val fileName    = pendingUploadName.ifBlank { "document.txt" }
                        val displayName = pendingDisplayName.trim().ifBlank { fileName }

                        coroutineScope.launch {
                            isUploading = true
                            processingStage = ""
                            processingProgress = 0
                            uploadMsg = "Đang upload..."
                            try {
                                val res = uploadDocument(
                                    context     = context,
                                    baseUrl     = baseUrl,
                                    uri         = uploadUri,
                                    filename    = fileName,
                                    displayName = displayName,
                                    fileType    = pendingFileType,
                                    subject     = filterSubj,
                                )

                                val emptyOrWarningIngest = !res.warning.isNullOrBlank() || (res.success && res.chunks == 0)

                                if (emptyOrWarningIngest) {
                                    ingestWarningText = res.warning?.takeIf { it.isNotBlank() }
                                        ?: "File này không có text layer hoặc không trích xuất được nội dung nên chưa tạo chunk nào."
                                    showIngestWarning = true
                                    uploadMsg = "Upload xong: kiểm tra cảnh báo"
                                    pendingUploadUri = null
                                    pendingUploadName = ""
                                    pendingDisplayName = ""
                                    pendingFileType = "txt"
                                } else if (!res.success) {
                                    uploadMsg = "Upload thất bại (HTTP ${res.status})"
                                } else {
                                    // Success or background processing
                                    uploadMsg = if (res.status == 202) "Upload xong, xử lý nền..." else "Upload thành công ✓"
                                }

                                // If server created a doc id, start polling for processing progress
                                val docId = res.id
                                if (docId != null && !emptyOrWarningIngest) {
                                    processingStage = if (res.indexed == true) "Hoàn tất" else "Chờ xử lý"
                                    // Poll until vectors equal chunk count or timeout (interval=1s, timeout=10min)
                                    pollDocumentStatus(baseUrl, docId, onUpdate = { stage, percent ->
                                        processingStage = stage
                                        processingProgress = percent
                                    }, pollIntervalMs = 1000L, timeoutMs = 10 * 60 * 1000L)
                                }

                                loadDocs()
                                loadHealth()
                                onRefreshStats()
                            } catch (e: Exception) {
                                uploadMsg = "Lỗi: ${e.message?.take(40)}"
                                Log.e("KB", "Upload error: ${e.message}")
                            } finally {
                                isUploading = false
                                pendingUploadUri = null
                                pendingUploadName = ""
                                pendingDisplayName = ""
                                pendingFileType = "txt"
                                delay(3000)
                                uploadMsg = ""
                                processingStage = ""
                                processingProgress = 0
                            }
                        }
                    },
                    shape  = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor         = Teal,
                        contentColor           = BgDeep,
                        disabledContainerColor = TealDim,
                        disabledContentColor   = TextMuted,
                    ),
                ) {
                    Text(
                        if (isUploading) "Đang upload..." else "Upload",
                        fontWeight = FontWeight.Bold,
                        fontSize = 13.sp,
                    )
                }
            },
            dismissButton = {
                TextButton(
                    enabled = !isUploading,
                    onClick = {
                        pendingUploadUri = null
                        pendingUploadName = ""
                        pendingDisplayName = ""
                        pendingFileType = "txt"
                    },
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Text("Huỷ", color = TextMuted, fontWeight = FontWeight.Medium)
                }
            },
        )
    }

    // Ingest warning dialog (when server returns warning like scan-only PDF)
    if (showIngestWarning) {
        AlertDialog(
            onDismissRequest = { showIngestWarning = false; ingestWarningText = "" },
            containerColor   = BgCard,
            shape            = RoundedCornerShape(16.dp),
            title = { Text("Cảnh báo trích xuất", fontWeight = FontWeight.Bold, color = TextPrimary) },
            text = { Text(ingestWarningText, color = TextSecond) },
            confirmButton = {
                Button(onClick = { showIngestWarning = false; ingestWarningText = "" }) {
                    Text("OK")
                }
            }
        )
    }

    // Delete confirm dialog
    if (deleteConfirmId != null) {
        AlertDialog(
            onDismissRequest = { deleteConfirmId = null },
            containerColor   = BgCard,
            shape            = RoundedCornerShape(20.dp),
            titleContentColor = TextPrimary,
            textContentColor  = TextSecond,
            title = {
                Text("Xoá tài liệu?", fontWeight = FontWeight.Bold)
            },
            text = {
                Text(
                    "Tài liệu và toàn bộ chunks RAG sẽ bị xoá vĩnh viễn. Hành động này không thể hoàn tác.",
                    fontSize = 13.sp,
                    color = TextSecond,
                )
            },
            confirmButton = {
                Button(
                    onClick = {
                        val id = deleteConfirmId!!
                        deleteConfirmId = null
                        coroutineScope.launch {
                            val ok = deleteDocument(baseUrl, id)
                            if (ok) { loadHealth(); onRefreshStats() }
                            loadDocs()
                        }
                    },
                    shape  = RoundedCornerShape(12.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Red,
                        contentColor   = Color.White,
                    ),
                ) {
                    Text("Xoá", fontWeight = FontWeight.Bold)
                }
            },
            dismissButton = {
                TextButton(onClick = { deleteConfirmId = null }, shape = RoundedCornerShape(12.dp)) {
                    Text("Huỷ", color = TextMuted)
                }
            },
        )
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(horizontal = 16.dp)
            .padding(top = 20.dp, bottom = 16.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        // ── Header row ───────────────────────────────────────────────────────
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text(
                    "Knowledge Base",
                    fontSize   = 22.sp,
                    fontWeight = FontWeight.Bold,
                    color      = TextPrimary,
                    letterSpacing = (-0.3).sp,
                )
                Spacer(Modifier.height(2.dp))
                Text(
                    "${totalDocs} tài liệu · ${totalChunks} chunks",
                    fontSize = 12.sp,
                    color    = TextMuted,
                )
            }
            // Upload button
            Button(
                onClick  = { fileLauncher.launch("*/*") },
                enabled  = !isUploading,
                shape    = RoundedCornerShape(14.dp),
                colors   = ButtonDefaults.buttonColors(
                    containerColor         = Teal,
                    contentColor           = BgDeep,
                    disabledContainerColor = TealDim,
                    disabledContentColor   = TextMuted,
                ),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 10.dp),
            ) {
                Text(
                    text       = if (isUploading) "Uploading..." else "+ Upload",
                    fontWeight = FontWeight.Bold,
                    fontSize   = 13.sp,
                )
            }
        }

        // ── Upload status banner ─────────────────────────────────────────────
        if (uploadMsg.isNotBlank()) {
            val isSuccess = uploadMsg.contains("✓")
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .clip(RoundedCornerShape(12.dp))
                    .background(if (isSuccess) GreenDim else AmberDim)
                    .border(1.dp, if (isSuccess) GreenBorder else Color(0x40FFBE57), RoundedCornerShape(12.dp))
                    .padding(horizontal = 14.dp, vertical = 10.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    if (isSuccess) "✓" else "⚠",
                    fontSize   = 14.sp,
                    color      = if (isSuccess) Green else Amber,
                    fontWeight = FontWeight.Bold,
                )
                Spacer(Modifier.width(8.dp))
                Text(
                    uploadMsg,
                    fontSize   = 12.sp,
                    fontWeight = FontWeight.Medium,
                    color      = if (isSuccess) Green else Amber,
                )
            }
        }

        if (processingStage.isNotBlank()) {
            Column(modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
                Row(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(10.dp))
                        .background(BgCardAlt)
                        .border(1.dp, BorderMid, RoundedCornerShape(10.dp))
                        .padding(10.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Text("⏳", fontSize = 14.sp, color = Teal)
                    Spacer(Modifier.width(8.dp))
                    Text(processingStage, fontSize = 12.sp, color = TextPrimary, modifier = Modifier.weight(1f))
                    if (processingProgress in 1..100) {
                        Text("${processingProgress}%", fontSize = 12.sp, color = TextSecond)
                    }
                }
                Spacer(Modifier.height(6.dp))
                if (processingProgress in 1..99) {
                    LinearProgressIndicator(progress = processingProgress / 100f, modifier = Modifier.fillMaxWidth().height(6.dp))
                } else {
                    LinearProgressIndicator(modifier = Modifier.fillMaxWidth().height(6.dp))
                }
            }
        }

        // ── Filter row ───────────────────────────────────────────────────────
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            OutlinedTextField(
                value       = filterSubj,
                onValueChange = { filterSubj = it },
                placeholder = { Text("Lọc theo môn học...", fontSize = 12.sp, color = TextHint) },
                modifier    = Modifier.weight(1f).height(48.dp),
                singleLine  = true,
                textStyle   = LocalTextStyle.current.copy(fontSize = 12.sp, color = TextPrimary),
                colors      = OutlinedTextFieldDefaults.colors(
                    focusedBorderColor      = Teal,
                    unfocusedBorderColor    = BorderMid,
                    cursorColor             = Teal,
                    focusedContainerColor   = BgCard,
                    unfocusedContainerColor = BgCard,
                ),
                shape = RoundedCornerShape(12.dp),
            )
            Button(
                onClick = { loadDocs() },
                shape   = RoundedCornerShape(12.dp),
                colors  = ButtonDefaults.buttonColors(
                    containerColor = BgCard,
                    contentColor   = TextSecond,
                ),
                border  = BorderStroke(1.dp, BorderMid),
                modifier = Modifier.height(48.dp),
                contentPadding = PaddingValues(horizontal = 16.dp),
            ) {
                Text("Lọc", fontSize = 12.sp, fontWeight = FontWeight.Bold)
            }
        }

        if (documents.isNotEmpty()) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.spacedBy(8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    "Nguồn đang dùng: ${if (selectedDocIds.isEmpty()) "Tất cả file trong session" else "${selectedDocIds.size} file đã chọn"}",
                    fontSize = 12.sp,
                    color = TextSecond,
                    modifier = Modifier.weight(1f),
                )
                TextButton(
                    onClick = { onSelectedDocIdsChange(documents.mapTo(mutableSetOf()) { it.id }) },
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Text("Chọn tất cả", color = Teal, fontSize = 12.sp)
                }
                TextButton(
                    onClick = { onSelectedDocIdsChange(emptySet()) },
                    shape = RoundedCornerShape(12.dp),
                ) {
                    Text("Tất cả", color = TextMuted, fontSize = 12.sp)
                }
            }
        }

        // ── Stats chips ──────────────────────────────────────────────────────
        Row(
            modifier = Modifier.fillMaxWidth(),
            horizontalArrangement = Arrangement.spacedBy(6.dp),
        ) {
            val localChunks = documents.sumOf { it.chunkCount }
            val localSizeKb = documents.sumOf { it.fileSize } / 1024
            KbStatChip("${documents.size} hiển thị", Teal)
            KbStatChip("$localChunks chunks", Purple)
            KbStatChip("${localSizeKb} KB", TextMuted)
        }

        // ── Document list ────────────────────────────────────────────────────
        when {
            isLoading -> {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .padding(top = 48.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(12.dp),
                    ) {
                        CircularProgressIndicator(
                            color       = Teal,
                            strokeWidth = 2.dp,
                            modifier    = Modifier.size(32.dp),
                        )
                        Text("Đang tải tài liệu...", fontSize = 13.sp, color = TextMuted)
                    }
                }
            }
            documents.isEmpty() -> {
                Box(
                    modifier = Modifier
                        .fillMaxWidth()
                        .clip(RoundedCornerShape(20.dp))
                        .background(BgCard)
                        .border(1.dp, BorderMid, RoundedCornerShape(20.dp))
                        .padding(vertical = 48.dp),
                    contentAlignment = Alignment.Center,
                ) {
                    Column(
                        horizontalAlignment = Alignment.CenterHorizontally,
                        verticalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(
                            "◈",
                            fontSize = 36.sp,
                            color    = TextHint,
                        )
                        Text(
                            "Chưa có tài liệu nào",
                            fontSize   = 15.sp,
                            fontWeight = FontWeight.SemiBold,
                            color      = TextSecond,
                        )
                        Text(
                            "Nhấn + Upload để thêm tài liệu",
                            fontSize = 12.sp,
                            color    = TextMuted,
                        )
                    }
                }
            }
            else -> {
                LazyColumn(
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                    modifier = Modifier.fillMaxSize(),
                ) {
                    items(documents, key = { it.id }) { doc ->
                        DocumentCard(
                            doc      = doc,
                            onDelete = { deleteConfirmId = doc.id },
                            selected = selectedDocIds.contains(doc.id),
                            onToggleSelected = {
                                onSelectedDocIdsChange(
                                    if (selectedDocIds.contains(doc.id)) selectedDocIds - doc.id else selectedDocIds + doc.id
                                )
                            },
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun KbStatChip(text: String, color: Color) {
    Box(
        modifier = Modifier
            .clip(RoundedCornerShape(8.dp))
            .background(color.copy(alpha = 0.08f))
            .border(0.5.dp, color.copy(alpha = 0.2f), RoundedCornerShape(8.dp))
            .padding(horizontal = 10.dp, vertical = 5.dp),
    ) {
        Text(
            text,
            fontSize   = 11.sp,
            fontWeight = FontWeight.Bold,
            color      = color.copy(alpha = 0.8f),
        )
    }
}

@Composable
fun DocumentCard(doc: KbDocument, onDelete: () -> Unit, selected: Boolean, onToggleSelected: () -> Unit) {
    val (fileLabel, iconColor) = when (doc.fileType.lowercase()) {
        "pdf"   -> Pair("PDF",  Teal)
        "txt"   -> Pair("TXT",  Green)
        "image" -> Pair("IMG",  Amber)
        else    -> Pair("DOC",  Purple)
    }
    val sizeKb    = doc.fileSize / 1024
    val dateShort = doc.uploadDate.take(10)

    Row(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(16.dp))
            .background(BgCard)
            .border(1.dp, BorderMid, RoundedCornerShape(16.dp))
            .padding(horizontal = 14.dp, vertical = 12.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        // File type badge
        Box(
            modifier = Modifier
                .size(44.dp)
                .clip(RoundedCornerShape(12.dp))
                .background(iconColor.copy(alpha = 0.1f))
                .border(1.dp, iconColor.copy(alpha = 0.2f), RoundedCornerShape(12.dp)),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text       = fileLabel,
                fontSize   = 11.sp,
                fontWeight = FontWeight.Black,
                color      = iconColor,
                letterSpacing = 0.5.sp,
            )
        }

        Spacer(Modifier.width(12.dp))

        Checkbox(
            checked = selected,
            onCheckedChange = { onToggleSelected() },
            colors = CheckboxDefaults.colors(
                checkedColor = Teal,
                uncheckedColor = TextHint,
                checkmarkColor = BgDeep,
            ),
        )

        Spacer(Modifier.width(6.dp))

        // Info column
        Column(modifier = Modifier.weight(1f)) {
            Text(
                text       = doc.displayName,
                fontSize   = 13.sp,
                fontWeight = FontWeight.SemiBold,
                color      = TextPrimary,
                maxLines   = 1,
                overflow   = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.height(4.dp))
            Row(
                horizontalArrangement = Arrangement.spacedBy(5.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                if (doc.subject.isNotBlank()) {
                    DocChip(doc.subject, Teal)
                }
                DocChip("${sizeKb}KB", TextMuted)
                DocChip(dateShort, TextHint)
            }
            if (doc.chunkCount > 0) {
                Spacer(Modifier.height(4.dp))
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(
                        modifier = Modifier
                            .size(5.dp)
                            .clip(CircleShape)
                            .background(Green),
                    )
                    Spacer(Modifier.width(5.dp))
                    Text(
                        "${doc.chunkCount} chunks · RAG ready",
                        fontSize   = 10.sp,
                        color      = Green.copy(alpha = 0.8f),
                        fontWeight = FontWeight.Medium,
                    )
                }
            }
        }

        Spacer(Modifier.width(8.dp))

        // Delete button
        val deleteInteraction = remember { MutableInteractionSource() }
        Box(
            modifier = Modifier
                .size(36.dp)
                .clip(RoundedCornerShape(10.dp))
                .background(RedDim)
                .border(1.dp, RedBorder, RoundedCornerShape(10.dp))
                .clickable(
                    interactionSource = deleteInteraction,
                    indication = ripple(bounded = true, color = Red),
                    onClick = onDelete,
                ),
            contentAlignment = Alignment.Center,
        ) {
            Text("✕", fontSize = 13.sp, color = Red, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
fun DocChip(text: String, color: Color) {
    Text(
        text = text,
        fontSize   = 10.sp,
        fontWeight = FontWeight.Medium,
        color      = color.copy(alpha = 0.75f),
        modifier   = Modifier
            .clip(RoundedCornerShape(5.dp))
            .background(color.copy(alpha = 0.08f))
            .padding(horizontal = 6.dp, vertical = 2.dp),
    )
}

// ── Network helpers ───────────────────────────────────────────────────────────
private fun resolveDisplayName(context: Context, uri: Uri): String {
    try {
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)
            ?.use { cursor ->
                if (cursor.moveToFirst()) {
                    val idx = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                    if (idx >= 0) {
                        val value = cursor.getString(idx)?.trim()
                        if (!value.isNullOrEmpty()) return value
                    }
                }
            }
    } catch (_: Exception) {}
    val fallback = uri.lastPathSegment?.substringAfterLast('/')?.trim().orEmpty()
    return if (fallback.isNotEmpty()) fallback else "document"
}

private suspend fun fetchDocuments(baseUrl: String, subject: String?): List<KbDocument> =
    withContext(Dispatchers.IO) {
        val urlStr = "$baseUrl/kb/documents" + if (!subject.isNullOrBlank()) "?subject=$subject" else ""
        val conn   = openConnection(urlStr, apiKey = DalapServerState.apiKey)
        val body   = conn.inputStream.bufferedReader().readText()
        conn.disconnect()
        val arr = JSONObject(body).getJSONArray("documents")
        (0 until arr.length()).map { i ->
            val obj = arr.getJSONObject(i)
            KbDocument(
                id           = obj.getInt("id"),
                originalName = obj.optString("original_name", ""),
                filename     = obj.optString("filename", ""),
                fileType     = obj.optString("file_type", "txt"),
                subject      = obj.optString("subject", ""),
                uploadDate   = obj.optString("upload_date", ""),
                fileSize     = obj.optLong("file_size", 0L),
                chunkCount   = obj.optInt("chunk_count", 0),
            )
        }
    }

private suspend fun uploadDocument(
    context: Context,
    baseUrl: String,
    uri: Uri,
    filename: String,
    displayName: String, fileType: String, subject: String,
): UploadResult = withContext(Dispatchers.IO) {
    val boundary = "Boundary-${System.currentTimeMillis()}"
    val conn = openConnection(
        "$baseUrl/kb/upload",
        method = "POST",
        apiKey = DalapServerState.apiKey,
        contentType = "multipart/form-data; boundary=$boundary",
    )

    try {
        conn.doOutput = true
        conn.outputStream.use { output ->
            val writer = output.bufferedWriter()

            fun writeField(name: String, value: String) {
                writer.write("--$boundary\r\n")
                writer.write("Content-Disposition: form-data; name=\"$name\"\r\n\r\n")
                writer.write(value)
                writer.write("\r\n")
            }

            writeField("display_name", displayName)
            writeField("file_type", fileType)
            writeField("subject", subject)
            writer.flush()

            output.write("--$boundary\r\n".toByteArray())
            output.write("Content-Disposition: form-data; name=\"file\"; filename=\"$filename\"\r\n".toByteArray())
            output.write("Content-Type: application/octet-stream\r\n\r\n".toByteArray())

            context.contentResolver.openInputStream(uri)?.use { input ->
                input.copyTo(output)
            } ?: return@withContext UploadResult(success = false, status = 0, warning = "Cannot open input stream")

            output.write("\r\n--$boundary--\r\n".toByteArray())
            output.flush()
        }

        val code = conn.responseCode
        val body = try {
            val stream = if (code in 200..299 || code == 202) conn.inputStream else conn.errorStream
            stream?.bufferedReader()?.use { it.readText() } ?: ""
        } catch (e: Exception) { "" }

        val json = try { if (body.isNotBlank()) JSONObject(body) else null } catch (e: Exception) { null }

        val id = json?.optInt("id", -1)?.takeIf { it >= 0 }
        val indexed = json?.optBoolean("indexed")
        val warning = json?.optString("warning", null) ?: json?.optString("note", null)
        val chunks = json?.optInt("chunks", -1)?.takeIf { it >= 0 }
        val vec = json?.optInt("vector_chunks", -1)?.takeIf { it >= 0 }
        UploadResult(success = (code in 200..299) || code == 202, status = code, id = id, indexed = indexed, warning = warning, note = json?.optString("note", null), chunks = chunks, vectorChunks = vec)
    } finally {
        conn.disconnect()
    }
}

private suspend fun deleteDocument(baseUrl: String, docId: Int): Boolean =
    withContext(Dispatchers.IO) {
        val conn = openConnection("$baseUrl/kb/documents/$docId", method = "DELETE", apiKey = DalapServerState.apiKey)
        val ok   = conn.responseCode in 200..299
        conn.disconnect()
        ok
    }

private suspend fun pollDocumentStatus(
    baseUrl: String,
    docId: Int,
    onUpdate: (stage: String, percent: Int) -> Unit,
    pollIntervalMs: Long = 1000L,
    timeoutMs: Long = 10 * 60 * 1000L,
) {
    withContext(Dispatchers.IO) {
        val start = System.currentTimeMillis()
        while (System.currentTimeMillis() - start < timeoutMs) {
            try {
                val conn = openConnection("$baseUrl/kb/documents/$docId", apiKey = DalapServerState.apiKey)
                val ok = conn.responseCode in 200..299
                if (ok) {
                    val body = conn.inputStream.bufferedReader().use { it.readText() }
                    val json = JSONObject(body)
                    val chunkCount = json.optInt("chunk_count", 0)
                    val vectorCount = json.optInt("vector_count", 0)

                    if (chunkCount <= 0) {
                        onUpdate("Chunking...", 0)
                    } else {
                        val percent = (if (chunkCount > 0) (vectorCount * 100 / chunkCount) else 0).coerceIn(0, 100)
                        if (percent >= 100) {
                            onUpdate("Hoàn tất", 100)
                            conn.disconnect()
                            return@withContext
                        } else {
                            onUpdate("Vectorizing: $vectorCount/$chunkCount", percent)
                        }
                    }
                }
                conn.disconnect()
            } catch (_: Exception) {
                // ignore transient errors
            }
            delay(pollIntervalMs)
        }
        onUpdate("Timeout", 0)
    }
}

private suspend fun fetchServerCounts(baseUrl: String): Pair<Int, Int>? =
    withContext(Dispatchers.IO) {
        val conn = openConnection("$baseUrl/health", apiKey = DalapServerState.apiKey)
        try {
            if (conn.responseCode !in 200..299) return@withContext null
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            val json = JSONObject(body)
            Pair(json.optInt("docs", 0), json.optInt("chunks", 0))
        } catch (e: Exception) {
            Log.w("DALAP", "Health fetch failed: ${e.message}")
            null
        } finally {
            conn.disconnect()
        }
    }

private fun openConnection(
    urlStr: String,
    method: String = "GET",
    apiKey: String = "",
    contentType: String = "application/json",
): HttpURLConnection {
    val trustAll = arrayOf(object : X509TrustManager {
        override fun checkClientTrusted(c: Array<X509Certificate>?, a: String?) {}
        override fun checkServerTrusted(c: Array<X509Certificate>?, a: String?) {}
        override fun getAcceptedIssuers() = arrayOf<X509Certificate>()
    })
    val ctx = SSLContext.getInstance("TLS")
    ctx.init(null, trustAll, SecureRandom())
    val conn = URL(urlStr).openConnection() as HttpURLConnection
    if (conn is HttpsURLConnection) {
        conn.sslSocketFactory = ctx.socketFactory
        conn.hostnameVerifier = HostnameVerifier { _, _ -> true }
    }
    conn.requestMethod = method
    conn.setRequestProperty("Content-Type", contentType)
    if (apiKey.isNotBlank()) conn.setRequestProperty("X-API-Key", apiKey)
    conn.connectTimeout = 8000
    conn.readTimeout    = 15000
    if (method.equals("POST", ignoreCase = true) || method.equals("PUT", ignoreCase = true) || method.equals("PATCH", ignoreCase = true)) {
        conn.doOutput = true
    }
    return conn
}

// ── DalapScreen entrypoint ────────────────────────────────────────────────────
@Composable
fun DalapScreen(
    status: String,
    url: String,
    docCount: Int,
    chunkCount: Int,
    onRefresh: () -> Unit,
    onOpenAR: () -> Unit,
) = MainApp(status, url, docCount, chunkCount, onRefresh, onOpenAR)

// ── App Header ────────────────────────────────────────────────────────────────
@Composable
fun AppHeader() {
    val infiniteTransition = rememberInfiniteTransition(label = "dot")
    val alpha by infiniteTransition.animateFloat(
        initialValue = 1f, targetValue = 0.25f,
        animationSpec = infiniteRepeatable(
            tween(1400, easing = EaseInOut), RepeatMode.Reverse
        ), label = "dotAlpha"
    )

    Row(
        verticalAlignment = Alignment.CenterVertically,
        modifier = Modifier.padding(top = 4.dp),
    ) {
        // Live indicator
        Box(
            modifier = Modifier
                .size(8.dp)
                .clip(CircleShape)
                .background(Green.copy(alpha = alpha))
        )
        Spacer(Modifier.width(10.dp))
        Column {
            Text(
                "DALAP AR",
                fontSize      = 22.sp,
                fontWeight    = FontWeight.Black,
                color         = TextPrimary,
                letterSpacing = (-0.5).sp,
            )
            Text(
                "LEARNING ASSISTANT",
                fontSize      = 10.sp,
                fontWeight    = FontWeight.Bold,
                color         = Teal,
                letterSpacing = 2.0.sp,
            )
        }
        Spacer(Modifier.weight(1f))
        // Version badge
        Box(
            modifier = Modifier
                .clip(RoundedCornerShape(8.dp))
                .background(TealDim)
                .border(1.dp, TealBorder, RoundedCornerShape(8.dp))
                .padding(horizontal = 8.dp, vertical = 4.dp)
        ) {
            Text(
                "v1.0",
                fontSize   = 11.sp,
                fontWeight = FontWeight.Bold,
                color      = Teal,
            )
        }
    }
}

// ── Server Status Card ────────────────────────────────────────────────────────
@Composable
fun ServerStatusCard(status: String) {
    val isRunning = status.contains("chạy", ignoreCase = true)
    val isError   = status.contains("lỗi",  ignoreCase = true)

    val accentColor = when {
        isRunning -> Green
        isError   -> Red
        else      -> Amber
    }
    val borderColor = accentColor.copy(alpha = 0.35f)
    val badgeBg     = accentColor.copy(alpha = 0.12f)
    val badgeText   = when {
        isRunning -> "Đang chạy"
        isError   -> "Lỗi"
        else      -> "Khởi động..."
    }

    val pulseTransition = rememberInfiniteTransition(label = "pulse")
    val dotAlpha by pulseTransition.animateFloat(
        initialValue = 1f, targetValue = 0.2f,
        animationSpec = infiniteRepeatable(
            tween(if (isRunning) 1400 else 500, easing = EaseInOut),
            RepeatMode.Reverse
        ), label = "pulseAlpha"
    )

    ArCard(borderColor = borderColor) {
        Row(
            verticalAlignment = Alignment.CenterVertically,
            modifier = Modifier.fillMaxWidth(),
        ) {
            Column(modifier = Modifier.weight(1f)) {
                SectionLabel("Trạng thái server")
                Spacer(Modifier.height(6.dp))
                Text(
                    text     = status,
                    fontSize = 13.sp,
                    color    = TextSecond,
                    maxLines = 2,
                    overflow = TextOverflow.Ellipsis,
                )
                Spacer(Modifier.height(4.dp))
                Text(
                    "Flask · Port 5000 · HTTPS",
                    fontSize = 11.sp,
                    color    = TextHint,
                )
            }
            Spacer(Modifier.width(12.dp))
            // Status badge
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier
                    .clip(RoundedCornerShape(20.dp))
                    .background(badgeBg)
                    .border(1.dp, borderColor, RoundedCornerShape(20.dp))
                    .padding(horizontal = 12.dp, vertical = 6.dp),
            ) {
                Box(
                    modifier = Modifier
                        .size(6.dp)
                        .clip(CircleShape)
                        .background(accentColor.copy(alpha = dotAlpha))
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    badgeText,
                    fontSize   = 12.sp,
                    fontWeight = FontWeight.Bold,
                    color      = accentColor,
                )
            }
        }
    }
}

// ── URL Card ──────────────────────────────────────────────────────────────────
@Composable
fun UrlCard(url: String) {
    val context = LocalContext.current
    var copied by remember { mutableStateOf(false) }
    val copyInteraction = remember { MutableInteractionSource() }

    LaunchedEffect(copied) {
        if (copied) { delay(2000); copied = false }
    }

    ArCard(borderColor = TealBorder.copy(alpha = 0.5f)) {
        SectionLabel("URL truy cập từ kính AR")
        Spacer(Modifier.height(10.dp))
        Row(
            modifier = Modifier
                .fillMaxWidth()
                .clip(RoundedCornerShape(10.dp))
                .background(TealDim)
                .border(1.dp, TealBorder.copy(alpha = 0.35f), RoundedCornerShape(10.dp))
                .clickable(
                    interactionSource = copyInteraction,
                    indication = ripple(bounded = true, color = Teal),
                ) {
                    val clipboard = context.getSystemService(Context.CLIPBOARD_SERVICE) as ClipboardManager
                    clipboard.setPrimaryClip(ClipData.newPlainText("DALAP URL", url))
                    copied = true
                }
                .padding(horizontal = 14.dp, vertical = 11.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Text(
                text       = if (url.isBlank()) "Đang lấy IP..." else url,
                fontSize   = 13.sp,
                fontWeight = FontWeight.Bold,
                fontFamily = FontFamily.Monospace,
                color      = Teal,
                modifier   = Modifier.weight(1f),
                maxLines   = 1,
                overflow   = TextOverflow.Ellipsis,
            )
            Spacer(Modifier.width(10.dp))
            AnimatedContent(targetState = copied, label = "copyAnim") { isCopied ->
                Text(
                    text       = if (isCopied) "✓ Đã sao chép" else "Nhấn để copy",
                    fontSize   = 11.sp,
                    fontWeight = if (isCopied) FontWeight.Bold else FontWeight.Normal,
                    color      = if (isCopied) Green else TextHint,
                )
            }
        }
        Spacer(Modifier.height(6.dp))
        Text(
            "Kính AR và server phải cùng WiFi",
            fontSize = 11.sp,
            color    = TextHint,
        )
    }
}

// ── Stats Row ─────────────────────────────────────────────────────────────────
@Composable
fun StatsRow(docCount: Int, chunkCount: Int) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        StatCard(
            label    = "Tài liệu",
            value    = docCount.toString(),
            accent   = Teal,
            icon     = "◧",
            modifier = Modifier.weight(1f),
        )
        StatCard(
            label    = "Chunks RAG",
            value    = chunkCount.toString(),
            accent   = Purple,
            icon     = "◈",
            modifier = Modifier.weight(1f),
        )
    }
}

@Composable
fun StatCard(
    label: String,
    value: String,
    accent: Color,
    icon: String,
    modifier: Modifier = Modifier,
) {
    Box(
        modifier = modifier
            .clip(RoundedCornerShape(16.dp))
            .background(BgCard)
            .border(1.dp, accent.copy(alpha = 0.15f), RoundedCornerShape(16.dp))
            .padding(horizontal = 14.dp, vertical = 14.dp)
    ) {
        Column {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    icon,
                    fontSize = 14.sp,
                    color    = accent.copy(alpha = 0.7f),
                )
                Spacer(Modifier.width(6.dp))
                Text(
                    label,
                    fontSize   = 11.sp,
                    color      = TextMuted,
                    fontWeight = FontWeight.Medium,
                )
            }
            Spacer(Modifier.height(6.dp))
            Text(
                value,
                fontSize   = 28.sp,
                fontWeight = FontWeight.Black,
                color      = accent,
                letterSpacing = (-0.5).sp,
            )
        }
    }
}

// ── Endpoints Card ────────────────────────────────────────────────────────────
@Composable
fun EndpointsCard() {
    data class Ep(val method: String, val path: String, val desc: String)
    val endpoints = listOf(
        Ep("POST", "/analyze",   "Vision OCR"),
        Ep("POST", "/ask",       "RAG hỏi đáp"),
        Ep("POST", "/chat",      "Voice chat"),
        Ep("POST", "/kb/upload", "Upload tài liệu"),
        Ep("GET",  "/",          "AR HUD"),
    )

    ArCard {
        SectionLabel("Endpoints hoạt động")
        Spacer(Modifier.height(10.dp))
        endpoints.forEachIndexed { i, ep ->
            Row(
                verticalAlignment = Alignment.CenterVertically,
                modifier = Modifier.fillMaxWidth(),
            ) {
                // Method badge — GET vs POST colour coded
                val methodColor = if (ep.method == "GET") Green else Teal
                Text(
                    text    = ep.method,
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Black,
                    color   = methodColor,
                    letterSpacing = 0.5.sp,
                    modifier = Modifier
                        .clip(RoundedCornerShape(5.dp))
                        .background(methodColor.copy(alpha = 0.1f))
                        .border(1.dp, methodColor.copy(alpha = 0.25f), RoundedCornerShape(5.dp))
                        .padding(horizontal = 7.dp, vertical = 3.dp),
                )
                Spacer(Modifier.width(10.dp))
                Text(
                    ep.path,
                    fontSize   = 12.sp,
                    fontFamily = FontFamily.Monospace,
                    color      = TextSecond.copy(alpha = 0.8f),
                    modifier   = Modifier.weight(1f),
                )
                Text(
                    ep.desc,
                    fontSize = 11.sp,
                    color    = TextMuted,
                )
            }
            if (i < endpoints.lastIndex) {
                HorizontalDivider(
                    modifier  = Modifier.padding(vertical = 8.dp),
                    thickness = 0.5.dp,
                    color     = Border,
                )
            }
        }
    }
}

// ── Action Buttons ────────────────────────────────────────────────────────────
@Composable
fun ActionButtons(onRefresh: () -> Unit, onOpenAR: () -> Unit, url: String) {
    Row(
        modifier = Modifier.fillMaxWidth(),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Button(
            onClick = onRefresh,
            modifier = Modifier.weight(1f).height(50.dp),
            shape  = RoundedCornerShape(14.dp),
            colors = ButtonDefaults.buttonColors(
                containerColor = TealDim,
                contentColor   = Teal,
            ),
            border = BorderStroke(1.dp, TealBorder),
        ) {
            Text(
                "↻  Làm mới",
                fontWeight    = FontWeight.Bold,
                fontSize      = 13.sp,
                letterSpacing = 0.3.sp,
            )
        }

        Button(
            onClick  = onOpenAR,
            enabled  = url.isNotBlank(),
            modifier = Modifier.weight(1f).height(50.dp),
            shape    = RoundedCornerShape(14.dp),
            colors   = ButtonDefaults.buttonColors(
                containerColor         = Teal,
                contentColor           = BgDeep,
                disabledContainerColor = BgCard,
                disabledContentColor   = TextHint,
            ),
            border = if (url.isNotBlank()) null
                     else BorderStroke(1.dp, BorderMid),
        ) {
            Text(
                "⬡  Mở AR HUD",
                fontWeight    = FontWeight.Bold,
                fontSize      = 13.sp,
                letterSpacing = 0.3.sp,
            )
        }
    }
}

// ── Shared components ─────────────────────────────────────────────────────────
@Composable
fun ArCard(
    borderColor: Color = BorderMid,
    content: @Composable ColumnScope.() -> Unit,
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .clip(RoundedCornerShape(18.dp))
            .background(BgCard)
            .border(1.dp, borderColor, RoundedCornerShape(18.dp))
            .padding(16.dp),
        content = content,
    )
}

@Composable
fun SectionLabel(text: String) {
    Text(
        text          = text.uppercase(),
        fontSize      = 10.sp,
        fontWeight    = FontWeight.Bold,
        color         = TextHint,
        letterSpacing = 1.2.sp,
    )
}

// ── Preview ───────────────────────────────────────────────────────────────────
@Preview(showBackground = true, backgroundColor = 0xFF060A16)
@Composable
fun DalapScreenPreview() {
    DaLAPTheme {
        DalapScreen(
            status     = "Server đang chạy",
            url        = "https://192.168.1.10:5000",
            docCount   = 7,
            chunkCount = 214,
            onRefresh  = {},
            onOpenAR   = {},
        )
    }
}

// Upload result returned by the server
data class UploadResult(
    val success: Boolean,
    val status: Int,
    val id: Int? = null,
    val indexed: Boolean? = null,
    val warning: String? = null,
    val note: String? = null,
    val chunks: Int? = null,
    val vectorChunks: Int? = null,
)