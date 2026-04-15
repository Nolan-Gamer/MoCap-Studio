/**
 * ═══════════════════════════════════════════════════════════════
 *  MoCap Studio — script.js
 *  Moteur : TensorFlow.js + MoveNet (SinglePose Lightning / Thunder)
 *  Fonctionnalités :
 *   - Accès webcam via getUserMedia
 *   - Inférence de pose en temps réel (requestAnimationFrame)
 *   - Dessin du squelette (keypoints + connections)
 *   - Affichage des coordonnées dans le panneau droit
 *   - Détection de gestes simples (mains levées, T-pose, bras croisés…)
 *   - Enregistrement des frames en JSON + export
 *   - FPS counter
 * ═══════════════════════════════════════════════════════════════
 */

// ─── Constantes MoveNet ──────────────────────────────────────────
/**
 * MoveNet retourne 17 keypoints indexés comme suit :
 * 0  nose          1  left_eye       2  right_eye
 * 3  left_ear      4  right_ear      5  left_shoulder
 * 6  right_shoulder 7  left_elbow    8  right_elbow
 * 9  left_wrist    10  right_wrist   11  left_hip
 * 12  right_hip    13  left_knee     14  right_knee
 * 15  left_ankle   16  right_ankle
 */
const KEYPOINT_NAMES = [
  'nose','left_eye','right_eye','left_ear','right_ear',
  'left_shoulder','right_shoulder','left_elbow','right_elbow',
  'left_wrist','right_wrist','left_hip','right_hip',
  'left_knee','right_knee','left_ankle','right_ankle'
];

// Connexions du squelette : paires [indexA, indexB]
const SKELETON_CONNECTIONS = [
  [0, 1],[0, 2],           // nez → yeux
  [1, 3],[2, 4],           // yeux → oreilles
  [5, 6],                  // épaule gauche ↔ droite
  [5, 7],[7, 9],           // bras gauche
  [6, 8],[8, 10],          // bras droit
  [5, 11],[6, 12],         // tronc (épaules → hanches)
  [11, 12],                // hanche gauche ↔ droite
  [11, 13],[13, 15],       // jambe gauche
  [12, 14],[14, 16]        // jambe droite
];

// Couleurs par segment (palette HUD)
const SEGMENT_COLORS = {
  head:   '#00dcc0',
  arms:   '#00b4d8',
  torso:  '#7b2d8b',
  legs:   '#f9a825'
};

// Quel groupe pour chaque connexion
const SEGMENT_MAP = [
  'head','head',
  'head','head',
  'torso',
  'arms','arms','arms','arms',
  'torso','torso','torso',
  'legs','legs','legs','legs'
];

// ─── État global ─────────────────────────────────────────────────
let detector      = null;   // instance du modèle MoveNet
let animFrameId   = null;   // ID requestAnimationFrame
let stream        = null;   // flux webcam
let isRunning     = false;  // caméra active
let isRecording   = false;  // enregistrement en cours
let recording     = [];     // tableau des frames enregistrées
let recStartTime  = 0;      // timestamp début enregistrement
let frameCount    = 0;      // compteur pour FPS
let lastFpsTime   = performance.now();
let gestureLog    = [];     // historique des gestes détectés

// Paramètres réglables
let confidenceThreshold = 0.35;
let showKeypoints  = true;
let showSkeleton   = true;
let showLabels     = true;
let detectGestures = true;
let mirrorMode     = true;

// ─── Éléments DOM ────────────────────────────────────────────────
const video          = document.getElementById('video');
const canvas         = document.getElementById('canvas');
const ctx            = canvas.getContext('2d');
const btnStart       = document.getElementById('btnStart');
const btnStop        = document.getElementById('btnStop');
const btnRecord      = document.getElementById('btnRecord');
const btnExport      = document.getElementById('btnExport');
const modelSelect    = document.getElementById('modelSelect');
const confidenceRange= document.getElementById('confidenceRange');
const confidenceVal  = document.getElementById('confidenceValue');
const togKeypoints   = document.getElementById('togKeypoints');
const togSkeleton    = document.getElementById('togSkeleton');
const togLabels      = document.getElementById('togLabels');
const togGestures    = document.getElementById('togGestures');
const togMirror      = document.getElementById('togMirror');
const fpsBadge       = document.getElementById('fpsBadge');
const statusBadge    = document.getElementById('statusBadge');
const modelBadge     = document.getElementById('modelBadge');
const videoRes       = document.getElementById('videoRes');
const inferenceTime  = document.getElementById('inferenceTime');
const poseCount      = document.getElementById('poseCount');
const keypointList   = document.getElementById('keypointList');
const keypointCount  = document.getElementById('keypointCount');
const gestureOverlay = document.getElementById('gestureOverlay');
const gestureLogEl   = document.getElementById('gestureLog');
const recStats       = document.getElementById('recStats');
const recFramesEl    = document.getElementById('recFrames');
const recDurationEl  = document.getElementById('recDuration');
const recordingSize  = document.getElementById('recordingSize');
const videoPlaceholder = document.getElementById('videoPlaceholder');

// ═══════════════════════════════════════════════════════════════
// INITIALISATION DU MODÈLE
// ═══════════════════════════════════════════════════════════════

/**
 * Charge le modèle MoveNet depuis le registre TF Hub.
 * Lightning = rapide (~50ms), Thunder = précis (~100ms)
 */
async function loadModel(variant = 'lightning') {
  setStatus('Chargement modèle…', 'loading');
  modelBadge.textContent = `MoveNet ${variant.charAt(0).toUpperCase() + variant.slice(1)}`;

  const modelType = variant === 'thunder'
    ? poseDetection.movenet.modelType.SINGLEPOSE_THUNDER
    : poseDetection.movenet.modelType.SINGLEPOSE_LIGHTNING;

  detector = await poseDetection.createDetector(
    poseDetection.SupportedModels.MoveNet,
    {
      modelType,
      enableSmoothing: true,   // lissage temporel des keypoints
      minPoseScore: 0.2        // seuil global de confiance de la pose
    }
  );
  console.log(`✓ Modèle MoveNet ${variant} chargé`);
}

// ═══════════════════════════════════════════════════════════════
// GESTION CAMÉRA
// ═══════════════════════════════════════════════════════════════

/**
 * Démarre la webcam et la boucle d'inférence.
 */
async function startCamera() {
  try {
    setStatus('Accès caméra…', 'loading');

    // Charger le modèle si pas encore fait
    if (!detector) await loadModel(modelSelect.value);

    // Demander accès webcam (préférer HD)
    stream = await navigator.mediaDevices.getUserMedia({
      video: { width: { ideal: 1280 }, height: { ideal: 720 }, facingMode: 'user' },
      audio: false
    });

    video.srcObject = stream;
    await new Promise(resolve => { video.onloadedmetadata = resolve; });
    await video.play();

    // Ajuster la taille du canvas à la vidéo
    canvas.width  = video.videoWidth;
    canvas.height = video.videoHeight;
    videoRes.textContent = `${video.videoWidth}×${video.videoHeight}`;

    video.classList.add('active');
    videoPlaceholder.classList.add('hidden');

    isRunning = true;
    setStatus('Actif', 'active');
    btnStart.disabled  = true;
    btnStop.disabled   = false;
    btnRecord.disabled = false;

    // Lancer la boucle d'animation
    detectLoop();
  } catch (err) {
    console.error('Erreur caméra :', err);
    setStatus('Erreur caméra', 'error');
    alert(`Impossible d'accéder à la caméra :\n${err.message}`);
  }
}

/**
 * Arrête tout (boucle + stream + enregistrement).
 */
function stopCamera() {
  isRunning = false;
  if (isRecording) stopRecording();

  cancelAnimationFrame(animFrameId);

  if (stream) {
    stream.getTracks().forEach(t => t.stop());
    stream = null;
  }

  video.srcObject = null;
  video.classList.remove('active');
  videoPlaceholder.classList.remove('hidden');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  setStatus('Arrêté', 'idle');
  btnStart.disabled  = false;
  btnStop.disabled   = true;
  btnRecord.disabled = true;
  keypointList.innerHTML = '<p class="no-data">Aucune donnée — démarrez la caméra.</p>';
  keypointCount.textContent = '(0)';
  poseCount.textContent = '0 pose(s) détectée(s)';
  gestureOverlay.innerHTML = '';
}

// ═══════════════════════════════════════════════════════════════
// BOUCLE D'INFÉRENCE PRINCIPALE
// ═══════════════════════════════════════════════════════════════

/**
 * Boucle requestAnimationFrame : inférence → dessin → affichage données.
 * requestAnimationFrame synchronise avec le rafraîchissement de l'écran
 * (généralement 60 fps) tout en laissant le navigateur gérer les pauses.
 */
async function detectLoop() {
  if (!isRunning) return;

  // ── Inférence ──────────────────────────────────────────────
  const t0 = performance.now();
  let poses = [];

  try {
    poses = await detector.estimatePoses(video, {
      flipHorizontal: false   // on gère le miroir manuellement
    });
  } catch (e) {
    console.warn('Erreur inférence :', e);
  }

  const inferMs = (performance.now() - t0).toFixed(1);
  inferenceTime.textContent = `Inférence : ${inferMs} ms`;
  poseCount.textContent = `${poses.length} pose(s) détectée(s)`;

  // ── Dessin ─────────────────────────────────────────────────
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  if (mirrorMode) {
    // Transformation miroir : flip horizontal autour du centre
    ctx.save();
    ctx.translate(canvas.width, 0);
    ctx.scale(-1, 1);
  }

  for (const pose of poses) {
    drawPose(pose);
  }

  if (mirrorMode) ctx.restore();

  // ── Affichage données ───────────────────────────────────────
  if (poses.length > 0) {
    updateKeypointPanel(poses[0].keypoints);
    if (detectGestures) detectAndShowGestures(poses[0].keypoints);

    // Enregistrement
    if (isRecording) {
      const elapsed = (performance.now() - recStartTime) / 1000;
      recording.push({
        timestamp: elapsed,
        keypoints: poses[0].keypoints.map(kp => ({
          name:  kp.name,
          x:     Math.round(kp.x),
          y:     Math.round(kp.y),
          score: +(kp.score).toFixed(3)
        }))
      });
      recFramesEl.textContent    = recording.length;
      recDurationEl.textContent  = `${elapsed.toFixed(1)} s`;
      recordingSize.textContent  = `REC: ${(JSON.stringify(recording).length / 1024).toFixed(1)} Ko`;
    }
  } else {
    gestureOverlay.innerHTML = '';
  }

  // ── FPS counter ─────────────────────────────────────────────
  frameCount++;
  const now = performance.now();
  if (now - lastFpsTime >= 500) {
    const fps = Math.round(frameCount / ((now - lastFpsTime) / 1000));
    fpsBadge.textContent = `${fps} FPS`;
    frameCount   = 0;
    lastFpsTime  = now;
  }

  // Prochain frame
  animFrameId = requestAnimationFrame(detectLoop);
}

// ═══════════════════════════════════════════════════════════════
// DESSIN DU SQUELETTE
// ═══════════════════════════════════════════════════════════════

/**
 * Dessine les keypoints et le squelette d'une pose détectée.
 * @param {Object} pose - Objet pose retourné par MoveNet
 */
function drawPose(pose) {
  const kps = pose.keypoints;

  // ── Lignes du squelette ────────────────────────────────────
  if (showSkeleton) {
    SKELETON_CONNECTIONS.forEach(([i, j], idx) => {
      const a = kps[i];
      const b = kps[j];

      // N'afficher que si les deux points ont assez de confiance
      if (!a || !b) return;
      if (a.score < confidenceThreshold || b.score < confidenceThreshold) return;

      const color = SEGMENT_COLORS[SEGMENT_MAP[idx]] || '#00dcc0';
      const alpha  = Math.min(a.score, b.score);

      ctx.save();
      ctx.globalAlpha = 0.4 + alpha * 0.6;
      ctx.strokeStyle = color;
      ctx.lineWidth   = 2.5;
      ctx.shadowColor = color;
      ctx.shadowBlur  = 10;
      ctx.lineCap     = 'round';

      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      ctx.restore();
    });
  }

  // ── Points clés (keypoints) ────────────────────────────────
  if (showKeypoints) {
    kps.forEach((kp, idx) => {
      if (!kp || kp.score < confidenceThreshold) return;

      const isHead = idx <= 4;
      const radius = isHead ? 5 : 4;
      const color  = isHead ? '#00dcc0' : '#ffffff';

      // Halo (glow)
      ctx.save();
      ctx.globalAlpha = kp.score * 0.7;
      ctx.fillStyle   = color;
      ctx.shadowColor = color;
      ctx.shadowBlur  = 14;
      ctx.beginPath();
      ctx.arc(kp.x, kp.y, radius + 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      // Point central solide
      ctx.save();
      ctx.globalAlpha = 0.9;
      ctx.fillStyle   = '#ffffff';
      ctx.beginPath();
      ctx.arc(kp.x, kp.y, radius, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      // Étiquette texte
      if (showLabels && kp.score > 0.6) {
        const label = KEYPOINT_NAMES[idx].replace('_', ' ');
        ctx.save();
        ctx.globalAlpha  = 0.8;
        ctx.fillStyle    = '#00dcc0';
        ctx.font         = '10px "Share Tech Mono", monospace';
        ctx.textAlign    = 'left';
        ctx.shadowColor  = '#000';
        ctx.shadowBlur   = 4;
        ctx.fillText(label, kp.x + 8, kp.y + 4);
        ctx.restore();
      }
    });
  }
}

// ═══════════════════════════════════════════════════════════════
// MISE À JOUR DU PANNEAU KEYPOINTS
// ═══════════════════════════════════════════════════════════════

/**
 * Génère dynamiquement la liste des keypoints avec leurs coordonnées.
 */
function updateKeypointPanel(keypoints) {
  keypointCount.textContent = `(${keypoints.length})`;

  keypointList.innerHTML = keypoints.map((kp, i) => {
    const conf = kp.score;
    const confClass = conf >= 0.7 ? 'high' : conf >= 0.4 ? 'mid' : 'low';
    const dimClass  = conf < confidenceThreshold ? 'low-conf' : '';

    // Coordonnées en tenant compte du miroir pour l'affichage
    const displayX = mirrorMode ? canvas.width - Math.round(kp.x) : Math.round(kp.x);
    const displayY = Math.round(kp.y);

    return `
      <div class="kp-item ${dimClass}" title="${KEYPOINT_NAMES[i]}">
        <span class="kp-name">${KEYPOINT_NAMES[i].replace(/_/g,' ')}</span>
        <span class="kp-coords">${displayX},${displayY}</span>
        <span class="kp-conf ${confClass}">${(conf*100).toFixed(0)}%</span>
      </div>`;
  }).join('');
}

// ═══════════════════════════════════════════════════════════════
// DÉTECTION DE GESTES
// ═══════════════════════════════════════════════════════════════

/**
 * Ensemble de règles heuristiques pour détecter des gestes courants.
 * On compare les positions relatives des keypoints.
 *
 * Keypoints utilisés :
 *  5  = left_shoulder  6  = right_shoulder
 *  9  = left_wrist    10  = right_wrist
 *  7  = left_elbow     8  = right_elbow
 * 11  = left_hip      12  = right_hip
 * 13  = left_knee     14  = right_knee
 */
function detectAndShowGestures(kps) {
  const gestures = [];

  // Raccourcis lisibles
  const get = (name) => kps[KEYPOINT_NAMES.indexOf(name)];
  const valid = (kp) => kp && kp.score >= confidenceThreshold;

  const lShoulder = get('left_shoulder');
  const rShoulder = get('right_shoulder');
  const lWrist    = get('left_wrist');
  const rWrist    = get('right_wrist');
  const lElbow    = get('left_elbow');
  const rElbow    = get('right_elbow');
  const lHip      = get('left_hip');
  const rHip      = get('right_hip');
  const lKnee     = get('left_knee');
  const rKnee     = get('right_knee');
  const nose      = get('nose');
  const lAnkle    = get('left_ankle');
  const rAnkle    = get('right_ankle');

  // ── Main gauche levée ──────────────────────────────────────
  if (valid(lWrist) && valid(lShoulder) && lWrist.y < lShoulder.y - 30) {
    gestures.push({ label: '✋ Main G. levée', type: 'normal' });
  }

  // ── Main droite levée ──────────────────────────────────────
  if (valid(rWrist) && valid(rShoulder) && rWrist.y < rShoulder.y - 30) {
    gestures.push({ label: '🤚 Main D. levée', type: 'normal' });
  }

  // ── Les deux mains levées ──────────────────────────────────
  if (valid(lWrist) && valid(rWrist) && valid(lShoulder) && valid(rShoulder)
      && lWrist.y < lShoulder.y - 30 && rWrist.y < rShoulder.y - 30) {
    // Remplacer les deux précédents par un seul message
    gestures.length = 0;  // reset
    gestures.push({ label: '🙌 Les deux mains levées', type: 'normal' });
  }

  // ── T-Pose (bras écartés horizontalement) ─────────────────
  if (valid(lElbow) && valid(rElbow) && valid(lShoulder) && valid(rShoulder)) {
    const shoulderWidth = Math.abs(lShoulder.x - rShoulder.x);
    const elbowY_diff_L = Math.abs(lElbow.y - lShoulder.y);
    const elbowY_diff_R = Math.abs(rElbow.y - rShoulder.y);
    if (elbowY_diff_L < 30 && elbowY_diff_R < 30 && shoulderWidth > 80) {
      gestures.push({ label: '✈ T-Pose', type: 'normal' });
    }
  }

  // ── Bras croisés ──────────────────────────────────────────
  // Si le poignet gauche est plus à droite que le poignet droit
  if (valid(lWrist) && valid(rWrist) && valid(lShoulder) && valid(rShoulder)) {
    const midX = (lShoulder.x + rShoulder.x) / 2;
    if (lWrist.x > midX && rWrist.x < midX &&
        lWrist.y < (lShoulder.y + 60) && rWrist.y < (rShoulder.y + 60)) {
      gestures.push({ label: '🙅 Bras croisés', type: 'warn' });
    }
  }

  // ── Accroupi / Squat ──────────────────────────────────────
  if (valid(lKnee) && valid(rKnee) && valid(lHip) && valid(rHip)) {
    const hipY   = (lHip.y + rHip.y) / 2;
    const kneeY  = (lKnee.y + rKnee.y) / 2;
    // Les genoux sont presque au niveau des hanches = accroupi
    if (kneeY - hipY < 50 && kneeY > hipY) {
      gestures.push({ label: '🏋 Squat/Accroupi', type: 'warn' });
    }
  }

  // ── Debout / Position neutre ───────────────────────────────
  if (gestures.length === 0 && valid(nose) && valid(lHip) && valid(rHip)) {
    gestures.push({ label: '🧍 Position neutre', type: 'normal' });
  }

  // ── Mise à jour overlay vidéo ──────────────────────────────
  gestureOverlay.innerHTML = gestures
    .map(g => `<div class="gesture-tag ${g.type === 'warn' ? 'warn' : ''}">${g.label}</div>`)
    .join('');

  // ── Journal des gestes (panneau droit) ─────────────────────
  // On n'enregistre que les changements significatifs
  const topGesture = gestures[0]?.label;
  const lastLogged = gestureLog[gestureLog.length - 1]?.label;

  if (topGesture && topGesture !== lastLogged) {
    const now = new Date();
    const timeStr = `${now.getHours()}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;
    gestureLog.push({ label: topGesture, time: timeStr });
    if (gestureLog.length > 20) gestureLog.shift(); // garder seulement les 20 derniers

    gestureLogEl.innerHTML = gestureLog.slice().reverse().map(e =>
      `<div class="gesture-entry">
        <span>${e.label}</span>
        <span class="time">${e.time}</span>
      </div>`
    ).join('');
  }
}

// ═══════════════════════════════════════════════════════════════
// ENREGISTREMENT & EXPORT
// ═══════════════════════════════════════════════════════════════

/**
 * Démarre ou arrête l'enregistrement.
 */
function toggleRecording() {
  if (!isRecording) {
    startRecording();
  } else {
    stopRecording();
  }
}

function startRecording() {
  recording     = [];
  recStartTime  = performance.now();
  isRecording   = true;
  btnRecord.textContent = '';
  btnRecord.innerHTML   = '<span class="rec-dot pulsing"></span> Stop enregistrement';
  btnRecord.classList.add('active');
  recStats.style.display = 'flex';
  statusBadge.textContent = 'REC';
  statusBadge.className   = 'badge badge-status recording';
  console.log('▶ Enregistrement démarré');
}

function stopRecording() {
  isRecording = false;
  btnRecord.innerHTML = '<span class="rec-dot"></span> Enregistrer';
  btnRecord.classList.remove('active');
  recStats.style.display = 'none';
  statusBadge.textContent = 'Actif';
  statusBadge.className   = 'badge badge-status active';
  btnExport.disabled = (recording.length === 0);
  console.log(`■ Enregistrement arrêté — ${recording.length} frames`);
}

/**
 * Exporte les données enregistrées en JSON téléchargeable.
 * Format :
 * {
 *   "meta": { "model": "lightning", "frameCount": 120, "duration": 4.0, ... },
 *   "frames": [ { "timestamp": 0.0, "keypoints": [...] }, ... ]
 * }
 */
function exportJSON() {
  if (recording.length === 0) {
    alert('Aucune donnée à exporter. Faites un enregistrement d\'abord.');
    return;
  }

  const exportData = {
    meta: {
      model:       modelSelect.value,
      frameCount:  recording.length,
      duration:    recording[recording.length - 1]?.timestamp ?? 0,
      resolution:  { width: canvas.width, height: canvas.height },
      exportedAt:  new Date().toISOString(),
      keypointNames: KEYPOINT_NAMES
    },
    frames: recording
  };

  const json = JSON.stringify(exportData, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `mocap_${new Date().toISOString().replace(/[:.]/g,'-')}.json`;
  a.click();
  URL.revokeObjectURL(url);

  console.log(`✓ Export JSON — ${(json.length/1024).toFixed(1)} Ko`);
}

/**
 * Envoie les données enregistrées au backend PHP pour sauvegarde serveur.
 * (Nécessite backend.php sur le même serveur)
 */
async function saveToServer() {
  if (recording.length === 0) return;

  const exportData = {
    model:      modelSelect.value,
    frameCount: recording.length,
    duration:   recording[recording.length - 1]?.timestamp ?? 0,
    frames:     recording
  };

  try {
    const res = await fetch('backend.php', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(exportData)
    });
    const data = await res.json();
    if (data.success) {
      console.log(`✓ Sauvegardé côté serveur : ${data.filename}`);
    } else {
      console.error('Erreur serveur :', data.error);
    }
  } catch (e) {
    console.warn('Backend PHP non disponible (mode local) :', e.message);
  }
}

// ═══════════════════════════════════════════════════════════════
// UTILITAIRES UI
// ═══════════════════════════════════════════════════════════════

/**
 * Met à jour le badge de statut.
 * @param {string} text   - Texte du badge
 * @param {string} state  - 'active' | 'loading' | 'idle' | 'error'
 */
function setStatus(text, state = 'idle') {
  statusBadge.textContent = text;
  statusBadge.className = 'badge badge-status';
  if (state === 'active')   statusBadge.classList.add('active');
  if (state === 'recording') statusBadge.classList.add('recording');
}

// ═══════════════════════════════════════════════════════════════
// EVENT LISTENERS
// ═══════════════════════════════════════════════════════════════

// Boutons caméra
btnStart.addEventListener('click', startCamera);
btnStop.addEventListener('click', stopCamera);

// Enregistrement / Export
btnRecord.addEventListener('click', toggleRecording);
btnExport.addEventListener('click', () => {
  exportJSON();
  saveToServer(); // tentative PHP (silencieuse si indispo)
});

// Sélecteur de modèle : recharge le modèle à la volée
modelSelect.addEventListener('change', async () => {
  const wasRunning = isRunning;
  if (wasRunning) stopCamera();
  detector = null;
  await loadModel(modelSelect.value);
  if (wasRunning) await startCamera();
});

// Seuil de confiance
confidenceRange.addEventListener('input', () => {
  confidenceThreshold = parseFloat(confidenceRange.value);
  confidenceVal.textContent = confidenceThreshold.toFixed(2);
});

// Toggles visuels
togKeypoints.addEventListener('change', () => { showKeypoints  = togKeypoints.checked; });
togSkeleton.addEventListener('change',  () => { showSkeleton   = togSkeleton.checked; });
togLabels.addEventListener('change',    () => { showLabels     = togLabels.checked; });
togGestures.addEventListener('change',  () => { detectGestures = togGestures.checked; if(!detectGestures) gestureOverlay.innerHTML=''; });
togMirror.addEventListener('change',    () => { mirrorMode     = togMirror.checked; });

// Redimensionnement fenêtre : adapter le canvas
window.addEventListener('resize', () => {
  if (isRunning) {
    canvas.width  = video.videoWidth;
    canvas.height = video.videoHeight;
  }
});

// ─── Préchargement du modèle au démarrage ───────────────────────
// On charge le modèle en arrière-plan dès le chargement de la page
// pour que le démarrage de la caméra soit quasi-instantané.
window.addEventListener('DOMContentLoaded', async () => {
  setStatus('Chargement…', 'loading');
  try {
    await loadModel(modelSelect.value);
    setStatus('Prêt', 'idle');
  } catch(e) {
    console.error('Erreur chargement modèle :', e);
    setStatus('Erreur modèle', 'error');
  }
});
