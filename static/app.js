// ── Element refs ─────────────────────────────────────────────────────────────
const shell         = document.getElementById('shell');
const handle        = document.getElementById('handle');
const fileInput     = document.getElementById('fileInput');
const uploadZone    = document.getElementById('uploadZone');
const previewWrap   = document.getElementById('previewWrap');
const previewImg    = document.getElementById('previewImg');
const clearBtn      = document.getElementById('clearBtn');
const analyzeBtn    = document.getElementById('analyzeBtn');
const camBtn        = document.getElementById('camBtn');
const camWrap       = document.getElementById('camWrap');
const camVideo      = document.getElementById('camVideo');
const captureBtn    = document.getElementById('captureBtn');
const stopCamBtn    = document.getElementById('stopCamBtn');
const subjectSelect = document.getElementById('subject');
const noteInput     = document.getElementById('noteInput');
const emptyState    = document.getElementById('emptyState');
const loadingWrap   = document.getElementById('loadingWrap');
const loadingText   = document.getElementById('loadingText');
const errorCard     = document.getElementById('errorCard');
const resultSection = document.getElementById('resultSection');
const extractedText = document.getElementById('extractedText');
const hintText      = document.getElementById('hintText');
const subjectTag    = document.getElementById('subjectTag');
const resetBtn      = document.getElementById('resetBtn');

// ── State ─────────────────────────────────────────────────────────────────────
let currentImageB64 = null;
let cameraStream    = null;

const LOADING_MESSAGES = [
  'Sending to Groq vision...',
  'Analyzing image content...',
  'Generating guidance...'
];

// ── Panel toggle ──────────────────────────────────────────────────────────────
handle.addEventListener('click', () => {
  shell.classList.toggle('collapsed');
});

// ── Image upload ──────────────────────────────────────────────────────────────
fileInput.addEventListener('change', e => {
  const file = e.target.files[0];
  if (file) loadImageFile(file);
});

uploadZone.addEventListener('dragover', e => {
  e.preventDefault();
  uploadZone.classList.add('drag');
});
uploadZone.addEventListener('dragleave', () => {
  uploadZone.classList.remove('drag');
});
uploadZone.addEventListener('drop', e => {
  e.preventDefault();
  uploadZone.classList.remove('drag');
  const file = e.dataTransfer.files[0];
  if (file && file.type.startsWith('image/')) loadImageFile(file);
});

function loadImageFile(file) {
  const reader = new FileReader();
  reader.onload = ev => {
    currentImageB64           = ev.target.result;
    previewImg.src            = currentImageB64;
    previewWrap.style.display = 'block';
    uploadZone.style.display  = 'none';
    analyzeBtn.disabled       = false;
    stopCamera();
  };
  reader.readAsDataURL(file);
}

clearBtn.addEventListener('click', resetImage);

function resetImage() {
  currentImageB64           = null;
  previewImg.src            = '';
  previewWrap.style.display = 'none';
  uploadZone.style.display  = 'block';
  analyzeBtn.disabled       = true;
  fileInput.value           = '';
}

// ── Camera ────────────────────────────────────────────────────────────────────
camBtn.addEventListener('click', async () => {
  try {
    cameraStream = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: 'environment' }
    });
    camVideo.srcObject    = cameraStream;
    camWrap.style.display = 'block';
    camBtn.style.display  = 'none';
  } catch (err) {
    showError('Camera access denied: ' + err.message);
  }
});

captureBtn.addEventListener('click', () => {
  const canvas  = document.createElement('canvas');
  canvas.width  = camVideo.videoWidth;
  canvas.height = camVideo.videoHeight;
  canvas.getContext('2d').drawImage(camVideo, 0, 0);

  currentImageB64           = canvas.toDataURL('image/jpeg', 0.92);
  previewImg.src            = currentImageB64;
  previewWrap.style.display = 'block';
  analyzeBtn.disabled       = false;
  stopCamera();
});

stopCamBtn.addEventListener('click', stopCamera);

function stopCamera() {
  if (cameraStream) {
    cameraStream.getTracks().forEach(track => track.stop());
    cameraStream = null;
  }
  camWrap.style.display = 'none';
  camBtn.style.display  = 'block';
}

// ── Analyze ───────────────────────────────────────────────────────────────────
analyzeBtn.addEventListener('click', runAnalysis);

async function runAnalysis() {
  if (!currentImageB64) return;

  // Auto-open right panel
  shell.classList.remove('collapsed');

  // Reset right panel state
  emptyState.style.display    = 'none';
  resultSection.style.display = 'none';
  errorCard.style.display     = 'none';
  loadingWrap.style.display   = 'flex';
  analyzeBtn.disabled         = true;

  // Cycle loading messages
  let msgIdx   = 0;
  const timer  = setInterval(() => {
    msgIdx = (msgIdx + 1) % LOADING_MESSAGES.length;
    loadingText.textContent = LOADING_MESSAGES[msgIdx];
  }, 1200);

  try {
    const response = await fetch('/analyze', {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        image:   currentImageB64,
        subject: subjectSelect.value,
        note:    noteInput.value.trim()
      })
    });

    const data = await response.json();
    clearInterval(timer);

    if (!response.ok || data.error) {
      showError(data.error || 'Unknown error from server.');
      return;
    }

    renderResults(data);

  } catch (err) {
    clearInterval(timer);
    showError('Could not reach server. Is app.py running on port 5000?');
  } finally {
    analyzeBtn.disabled = false;
  }
}

function renderResults(data) {
  extractedText.textContent = data.extracted_text || '(No text detected)';
  hintText.textContent      = data.hint           || '(No hint generated)';
  subjectTag.textContent    = data.subject        || 'General';
  subjectTag.style.display  = data.subject ? '' : 'none';

  loadingWrap.style.display   = 'none';
  resultSection.style.display = 'flex';
}

// ── Error display ─────────────────────────────────────────────────────────────
function showError(message) {
  loadingWrap.style.display = 'none';
  emptyState.style.display  = 'none';
  errorCard.style.display   = 'block';
  errorCard.textContent     = 'Error: ' + message;
}

// ── Reset ─────────────────────────────────────────────────────────────────────
resetBtn.addEventListener('click', () => {
  resultSection.style.display = 'none';
  emptyState.style.display    = 'flex';
  resetImage();
});
