<?php
/**
 * ═══════════════════════════════════════════════════════════════
 *  MoCap Studio — backend.php
 *  Rôle : Recevoir et sauvegarder les enregistrements de motion capture
 *         envoyés depuis script.js (fetch POST JSON)
 *
 *  Fonctionnement :
 *   1. Reçoit un POST JSON depuis le client
 *   2. Valide et assainit les données
 *   3. Sauvegarde dans /recordings/ avec un nom horodaté
 *   4. Retourne un JSON { success, filename, size } ou { success, error }
 *
 *  Comment lancer :
 *   - php -S localhost:8080  (serveur de dev PHP intégré)
 *   - Ou placer sur Apache/Nginx avec PHP activé
 * ═══════════════════════════════════════════════════════════════
 */

// ─── Configuration ───────────────────────────────────────────────
define('RECORDINGS_DIR',  __DIR__ . '/recordings/');
define('MAX_FILE_SIZE_MB', 50);    // taille max d'un enregistrement
define('ALLOWED_MODELS',   ['lightning', 'thunder']);

// ─── En-têtes HTTP ───────────────────────────────────────────────
header('Content-Type: application/json; charset=utf-8');
header('Access-Control-Allow-Origin: *');            // CORS pour dev local
header('Access-Control-Allow-Methods: POST, GET, OPTIONS');
header('Access-Control-Allow-Headers: Content-Type');

// Pré-requête CORS (navigateurs modernes)
if ($_SERVER['REQUEST_METHOD'] === 'OPTIONS') {
    http_response_code(200);
    exit;
}

// ─── Routage ─────────────────────────────────────────────────────
$method = $_SERVER['REQUEST_METHOD'];
$action = $_GET['action'] ?? '';

try {
    if ($method === 'GET' && $action === 'list') {
        echo json_encode(listRecordings());
    } elseif ($method === 'GET' && $action === 'download') {
        downloadRecording($_GET['file'] ?? '');
    } elseif ($method === 'DELETE' && $action === 'delete') {
        echo json_encode(deleteRecording($_GET['file'] ?? ''));
    } elseif ($method === 'POST') {
        echo json_encode(saveRecording());
    } else {
        throw new RuntimeException('Méthode ou action non supportée.', 400);
    }
} catch (RuntimeException $e) {
    http_response_code($e->getCode() ?: 500);
    echo json_encode(['success' => false, 'error' => $e->getMessage()]);
}

// ═══════════════════════════════════════════════════════════════
// SAUVEGARDER UN ENREGISTREMENT
// ═══════════════════════════════════════════════════════════════

/**
 * Reçoit le JSON de motion capture et le sauvegarde dans /recordings/.
 * @return array Résultat de l'opération
 */
function saveRecording(): array {
    // Lire le body JSON brut
    $rawInput = file_get_contents('php://input');
    if (empty($rawInput)) {
        throw new RuntimeException('Corps de requête vide.', 400);
    }

    // Vérifier la taille
    $sizeMB = strlen($rawInput) / (1024 * 1024);
    if ($sizeMB > MAX_FILE_SIZE_MB) {
        throw new RuntimeException("Fichier trop grand ({$sizeMB:.1f} Mo > " . MAX_FILE_SIZE_MB . " Mo).", 413);
    }

    // Décoder et valider
    $data = json_decode($rawInput, true);
    if (json_last_error() !== JSON_ERROR_NONE) {
        throw new RuntimeException('JSON invalide : ' . json_last_error_msg(), 400);
    }

    // Validation minimale du schéma
    if (!isset($data['frames']) || !is_array($data['frames'])) {
        throw new RuntimeException('Structure JSON invalide : "frames" manquant.', 422);
    }
    if (count($data['frames']) === 0) {
        throw new RuntimeException('Aucune frame à sauvegarder.', 422);
    }

    // Valider le modèle si présent
    $model = $data['model'] ?? 'unknown';
    if (!in_array($model, ALLOWED_MODELS, true)) {
        $model = 'unknown';  // on accepte quand même, on sanitize
    }

    // Créer le dossier recordings si nécessaire
    ensureRecordingsDir();

    // Générer un nom de fichier sécurisé et unique
    $date     = date('Y-m-d_H-i-s');
    $frames   = count($data['frames']);
    $duration = round($data['duration'] ?? 0, 2);
    $filename = "mocap_{$date}_f{$frames}_{$model}.json";
    $filepath = RECORDINGS_DIR . $filename;

    // Enrichir les métadonnées avant sauvegarde
    $data['meta'] = array_merge($data['meta'] ?? [], [
        'savedAt'    => date('c'),
        'serverFile' => $filename,
        'serverIP'   => anonymizeIP($_SERVER['REMOTE_ADDR'] ?? 'unknown'),
    ]);

    // Écriture du fichier
    $jsonOutput = json_encode($data, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
    $written    = file_put_contents($filepath, $jsonOutput, LOCK_EX);

    if ($written === false) {
        throw new RuntimeException('Impossible d\'écrire le fichier sur le serveur.', 500);
    }

    // Log serveur
    error_log("[MoCap] Enregistrement sauvegardé : $filename ({$sizeMB:.2f} Mo, $frames frames, {$duration}s)");

    return [
        'success'  => true,
        'filename' => $filename,
        'frames'   => $frames,
        'duration' => $duration,
        'size'     => round($written / 1024, 1) . ' Ko',
        'url'      => "?action=download&file=" . urlencode($filename),
    ];
}

// ═══════════════════════════════════════════════════════════════
// LISTER LES ENREGISTREMENTS
// ═══════════════════════════════════════════════════════════════

/**
 * Retourne la liste des enregistrements existants (GET ?action=list).
 * @return array
 */
function listRecordings(): array {
    ensureRecordingsDir();

    $files = glob(RECORDINGS_DIR . 'mocap_*.json');
    $list  = [];

    foreach ($files as $filepath) {
        $filename = basename($filepath);
        $size     = filesize($filepath);
        $mtime    = filemtime($filepath);

        // Lire uniquement les métadonnées (début du fichier)
        $meta = readMeta($filepath);

        $list[] = [
            'filename' => $filename,
            'size'     => round($size / 1024, 1) . ' Ko',
            'created'  => date('d/m/Y H:i:s', $mtime),
            'frames'   => $meta['frameCount'] ?? '?',
            'duration' => ($meta['duration'] ?? '?') . ' s',
            'model'    => $meta['model'] ?? '?',
        ];
    }

    // Tri par date décroissante
    usort($list, fn($a, $b) => strcmp($b['created'], $a['created']));

    return [
        'success' => true,
        'count'   => count($list),
        'files'   => $list,
    ];
}

// ═══════════════════════════════════════════════════════════════
// TÉLÉCHARGER UN ENREGISTREMENT
// ═══════════════════════════════════════════════════════════════

/**
 * Envoie un fichier JSON en téléchargement (GET ?action=download&file=...).
 */
function downloadRecording(string $filename): void {
    // Sécurité : interdire les traversées de répertoire
    $filename = basename($filename);
    if (!preg_match('/^mocap_[\w\-]+\.json$/', $filename)) {
        throw new RuntimeException('Nom de fichier invalide.', 400);
    }

    $filepath = RECORDINGS_DIR . $filename;
    if (!file_exists($filepath)) {
        throw new RuntimeException('Fichier introuvable.', 404);
    }

    // Envoyer en téléchargement
    header('Content-Type: application/json');
    header('Content-Disposition: attachment; filename="' . $filename . '"');
    header('Content-Length: ' . filesize($filepath));
    readfile($filepath);
    exit;
}

// ═══════════════════════════════════════════════════════════════
// SUPPRIMER UN ENREGISTREMENT
// ═══════════════════════════════════════════════════════════════

function deleteRecording(string $filename): array {
    $filename = basename($filename);
    if (!preg_match('/^mocap_[\w\-]+\.json$/', $filename)) {
        throw new RuntimeException('Nom de fichier invalide.', 400);
    }

    $filepath = RECORDINGS_DIR . $filename;
    if (!file_exists($filepath)) {
        throw new RuntimeException('Fichier introuvable.', 404);
    }

    unlink($filepath);
    return ['success' => true, 'deleted' => $filename];
}

// ═══════════════════════════════════════════════════════════════
// UTILITAIRES
// ═══════════════════════════════════════════════════════════════

/**
 * Crée le dossier recordings s'il n'existe pas.
 */
function ensureRecordingsDir(): void {
    if (!is_dir(RECORDINGS_DIR)) {
        if (!mkdir(RECORDINGS_DIR, 0755, true)) {
            throw new RuntimeException('Impossible de créer le dossier recordings/.', 500);
        }
        // Fichier .htaccess pour bloquer l'accès direct au navigateur
        file_put_contents(RECORDINGS_DIR . '.htaccess',
            "Options -Indexes\nDeny from all\n");
    }
}

/**
 * Lit les métadonnées d'un fichier JSON sans tout charger en mémoire.
 */
function readMeta(string $filepath): array {
    $handle = fopen($filepath, 'r');
    $preview = fread($handle, 2048); // lire les premiers 2 Ko suffit pour les meta
    fclose($handle);

    // Extraire le bloc "meta" via regex légère
    if (preg_match('/"meta"\s*:\s*(\{[^}]+\})/s', $preview, $m)) {
        $meta = json_decode($m[1], true);
        return $meta ?? [];
    }
    return [];
}

/**
 * Anonymise une adresse IP (RGPD) : garde seulement les 2 premiers octets.
 * Ex : 192.168.1.42 → 192.168.0.0
 */
function anonymizeIP(string $ip): string {
    if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV4)) {
        $parts = explode('.', $ip);
        return "{$parts[0]}.{$parts[1]}.0.0";
    }
    if (filter_var($ip, FILTER_VALIDATE_IP, FILTER_FLAG_IPV6)) {
        return substr($ip, 0, strrpos($ip, ':')) . ':0:0';
    }
    return 'unknown';
}
