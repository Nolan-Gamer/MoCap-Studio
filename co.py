"""
═══════════════════════════════════════════════════════════════
  MoCap Studio → Blender Importer
  Script Python à coller dans Blender > Scripting > Text Editor
  Testé sur Blender 3.x et 4.x

  Ce script fait 3 choses :
   1. Lit le fichier JSON exporté par MoCap Studio
   2. Crée un armature (squelette) avec 17 os (un par keypoint)
   3. Applique les positions frame par frame → keyframes d'animation

  STRUCTURE JSON attendue (notre format MoveNet) :
  {
    "meta": { "frameCount": 120, "duration": 4.0, ... },
    "frames": [
      {
        "timestamp": 0.0,
        "keypoints": [
          { "name": "nose", "x": 640, "y": 200, "score": 0.95 },
          ...
        ]
      }
    ]
  }

  UTILISATION :
   1. Ouvrir Blender
   2. Aller dans l'espace de travail "Scripting"
   3. Cliquer "New" pour créer un nouveau texte
   4. Coller ce script
   5. Modifier la variable JSON_FILE_PATH (ligne ~60)
   6. Appuyer sur le bouton ▶ "Run Script"
═══════════════════════════════════════════════════════════════
"""

import bpy
import json
import math
import os
from mathutils import Vector

# ─── ⚙️  CONFIGURATION — À MODIFIER ─────────────────────────────────
# Chemin vers votre fichier JSON exporté (absolu ou relatif au .blend)
JSON_FILE_PATH = "C:/Users/VotreNom/Downloads/mocap_2024-01-01_12-00-00.json"
# Sur Mac/Linux : "/Users/votreNom/Downloads/mocap_xxx.json"

# Facteur d'échelle : les coordonnées sont en pixels (ex: 1280×720)
# Blender travaille en mètres → on divise pour avoir des valeurs raisonnables
# Si votre armature est trop grande/petite, ajustez ce facteur.
SCALE_FACTOR = 0.005          # 1280px × 0.005 = 6.4 unités Blender

# Hauteur de référence pour normaliser la profondeur Y (la webcam est 2D)
# On crée une 3ème dimension Z artificielle à 0 (tout dans le plan XY)
VIDEO_WIDTH  = 1280           # résolution horizontale de l'enregistrement
VIDEO_HEIGHT = 720            # résolution verticale

# Seuil de confiance minimal : en dessous, le keypoint est ignoré
CONFIDENCE_THRESHOLD = 0.3

# FPS de l'animation Blender cible (indépendant du FPS de capture)
TARGET_FPS = 30

# Nom de l'armature créée dans Blender
ARMATURE_NAME = "MoCap_Armature"

# Hauteur de chaque os (en unités Blender) — purement visuel
BONE_LENGTH = 0.1

# ─── Connexions os (paires de keypoints pour former le squelette) ────
# Format : (nom_os, parent_nom_keypoint, enfant_nom_keypoint)
BONE_DEFINITIONS = [
    # Tête
    ("nose_to_left_eye",       "nose",           "left_eye"),
    ("nose_to_right_eye",      "nose",           "right_eye"),
    ("left_eye_to_ear",        "left_eye",       "left_ear"),
    ("right_eye_to_ear",       "right_eye",      "right_ear"),
    # Colonne vertébrale simulée (épaule → hanche via le milieu)
    ("shoulder_L",             "left_shoulder",  "left_elbow"),
    ("shoulder_R",             "right_shoulder", "right_elbow"),
    ("elbow_L",                "left_elbow",     "left_wrist"),
    ("elbow_R",                "right_elbow",    "right_wrist"),
    ("torso_L",                "left_shoulder",  "left_hip"),
    ("torso_R",                "right_shoulder", "right_hip"),
    ("hip_cross",              "left_hip",       "right_hip"),
    ("shoulder_cross",         "left_shoulder",  "right_shoulder"),
    ("thigh_L",                "left_hip",       "left_knee"),
    ("thigh_R",                "right_hip",      "right_knee"),
    ("shin_L",                 "left_knee",      "left_ankle"),
    ("shin_R",                 "right_knee",     "right_ankle"),
]

# ═══════════════════════════════════════════════════════════════
# FONCTIONS PRINCIPALES
# ═══════════════════════════════════════════════════════════════

def load_json(filepath: str) -> dict:
    """Charge et valide le fichier JSON MoCap Studio."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Fichier introuvable : {filepath}")

    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)

    if 'frames' not in data:
        raise ValueError("Format JSON invalide : clé 'frames' manquante.")

    print(f"✓ JSON chargé : {len(data['frames'])} frames")
    print(f"  Modèle : {data.get('meta', {}).get('model', 'inconnu')}")
    print(f"  Durée  : {data.get('meta', {}).get('duration', '?')} s")
    return data


def pixel_to_blender(x: float, y: float, 
                      video_w: int, video_h: int,
                      scale: float) -> Vector:
    """
    Convertit des coordonnées pixel 2D en coordonnées Blender 3D.
    
    Transformations appliquées :
     - Centrage : (0,0) pixel → (0,0) Blender (centre de l'image)
     - Inversion Y : en pixel Y↓ (haut=0), en Blender Y↑
     - Mise à l'échelle avec SCALE_FACTOR
     - Z = 0 (plan frontal, la webcam est 2D)
    """
    bx =  (x - video_w / 2) * scale
    by = -(y - video_h / 2) * scale   # inversion axe Y
    bz = 0.0
    return Vector((bx, bz, by))       # Blender : X=droite, Y=profondeur, Z=haut


def build_keypoint_index(frame: dict) -> dict:
    """Construit un dict {nom: keypoint} pour accès rapide."""
    return {kp['name']: kp for kp in frame['keypoints']}


def create_armature(name: str) -> tuple:
    """
    Crée un objet armature vide dans Blender et retourne (obj, armature).
    Si un objet du même nom existe déjà, il est supprimé.
    """
    # Supprimer l'ancienne armature si elle existe
    if name in bpy.data.objects:
        bpy.data.objects.remove(bpy.data.objects[name], do_unlink=True)

    # Créer la nouvelle armature
    arm_data = bpy.data.armatures.new(name)
    arm_obj  = bpy.data.objects.new(name, arm_data)
    bpy.context.collection.objects.link(arm_obj)

    # La sélectionner et l'activer
    bpy.context.view_layer.objects.active = arm_obj
    arm_obj.select_set(True)
    return arm_obj, arm_data


def add_bones(arm_obj, arm_data, first_frame_kps: dict):
    """
    Crée les os de l'armature basés sur les positions du 1er frame.
    Un os = un vecteur entre deux keypoints.
    """
    # Passer en mode Édition pour créer les os
    bpy.ops.object.mode_set(mode='EDIT')
    edit_bones = arm_data.edit_bones

    created_bones = {}

    for (bone_name, kp_head_name, kp_tail_name) in BONE_DEFINITIONS:
        kp_head = first_frame_kps.get(kp_head_name)
        kp_tail = first_frame_kps.get(kp_tail_name)

        if not kp_head or not kp_tail:
            continue
        if kp_head['score'] < CONFIDENCE_THRESHOLD or kp_tail['score'] < CONFIDENCE_THRESHOLD:
            continue

        bone = edit_bones.new(bone_name)
        bone.head = pixel_to_blender(kp_head['x'], kp_head['y'], 
                                      VIDEO_WIDTH, VIDEO_HEIGHT, SCALE_FACTOR)
        bone.tail = pixel_to_blender(kp_tail['x'], kp_tail['y'], 
                                      VIDEO_WIDTH, VIDEO_HEIGHT, SCALE_FACTOR)
        # Éviter les os de longueur zéro (Blender les supprime)
        if (bone.tail - bone.head).length < 0.001:
            bone.tail = bone.head + Vector((0, 0, BONE_LENGTH))

        created_bones[bone_name] = bone_name

    # Ajouter aussi des os "ponctuels" pour les keypoints isolés (nœuds)
    isolated_kps = ['nose', 'left_wrist', 'right_wrist', 'left_ankle', 'right_ankle']
    for kp_name in isolated_kps:
        kp = first_frame_kps.get(kp_name)
        if kp and kp['score'] >= CONFIDENCE_THRESHOLD:
            bone = edit_bones.new(f"kp_{kp_name}")
            pos  = pixel_to_blender(kp['x'], kp['y'], VIDEO_WIDTH, VIDEO_HEIGHT, SCALE_FACTOR)
            bone.head = pos
            bone.tail = pos + Vector((0, 0, BONE_LENGTH))

    # Repasser en mode Objet
    bpy.ops.object.mode_set(mode='OBJECT')
    print(f"✓ {len(edit_bones)} os créés dans l'armature")


def create_keypoints_as_empties(data: dict, scene: bpy.types.Scene):
    """
    Méthode alternative / complémentaire :
    Crée des objets "Empty" (croix) pour chaque keypoint,
    et les anime avec des keyframes.
    Utile pour vérifier les données brutes ou piloter des contraintes.
    """
    # Collection dédiée
    coll_name = "MoCap_Keypoints"
    if coll_name in bpy.data.collections:
        # Vider la collection existante
        old_coll = bpy.data.collections[coll_name]
        for obj in old_coll.objects:
            bpy.data.objects.remove(obj, do_unlink=True)
        bpy.data.collections.remove(old_coll)

    kp_collection = bpy.data.collections.new(coll_name)
    scene.collection.children.link(kp_collection)

    # Créer un Empty par keypoint
    empties = {}
    keypoint_names = [
        'nose','left_eye','right_eye','left_ear','right_ear',
        'left_shoulder','right_shoulder','left_elbow','right_elbow',
        'left_wrist','right_wrist','left_hip','right_hip',
        'left_knee','right_knee','left_ankle','right_ankle'
    ]

    for kp_name in keypoint_names:
        empty = bpy.data.objects.new(f"KP_{kp_name}", None)
        empty.empty_display_type = 'SPHERE'
        empty.empty_display_size = 0.05
        kp_collection.objects.link(empty)
        empties[kp_name] = empty

    # Animer les Empties frame par frame
    frames = data['frames']
    fps_ratio = TARGET_FPS / max(1, len(frames) / max(data['meta'].get('duration', 1), 0.001))

    for frame_idx, frame in enumerate(frames):
        blender_frame = int(frame_idx * (TARGET_FPS / 30)) + 1
        scene.frame_set(blender_frame)

        kp_index = build_keypoint_index(frame)

        for kp_name, empty in empties.items():
            kp = kp_index.get(kp_name)
            if not kp or kp['score'] < CONFIDENCE_THRESHOLD:
                continue

            pos = pixel_to_blender(kp['x'], kp['y'], VIDEO_WIDTH, VIDEO_HEIGHT, SCALE_FACTOR)
            empty.location = pos
            empty.keyframe_insert(data_path='location', frame=blender_frame)

    # Revenir au frame 1
    scene.frame_set(1)
    print(f"✓ {len(empties)} Empties animés sur {len(frames)} frames")
    return empties


def animate_armature(arm_obj, data: dict, scene: bpy.types.Scene):
    """
    Anime les os de l'armature en pose mode, frame par frame.
    Pour chaque frame JSON → 1 keyframe Blender.
    """
    frames   = data['frames']
    duration = data.get('meta', {}).get('duration', len(frames) / 30)
    n_frames = len(frames)

    # Configurer la timeline Blender
    scene.frame_start = 1
    scene.frame_end   = n_frames
    scene.render.fps  = TARGET_FPS

    # Activer l'armature et passer en Pose Mode
    bpy.context.view_layer.objects.active = arm_obj
    bpy.ops.object.mode_set(mode='POSE')
    pose_bones = arm_obj.pose.bones

    print(f"Animation : {n_frames} frames → {duration:.1f} s à {TARGET_FPS} FPS")

    for frame_idx, frame in enumerate(frames):
        blender_frame = frame_idx + 1
        scene.frame_set(blender_frame)

        kp_index = build_keypoint_index(frame)

        # Mettre à jour la position de chaque os via contrainte/location
        for (bone_name, kp_head_name, kp_tail_name) in BONE_DEFINITIONS:
            if bone_name not in pose_bones:
                continue

            kp_head = kp_index.get(kp_head_name)
            kp_tail = kp_index.get(kp_tail_name)

            if not kp_head or not kp_tail:
                continue
            if kp_head['score'] < CONFIDENCE_THRESHOLD:
                continue

            pbone = pose_bones[bone_name]
            pos   = pixel_to_blender(kp_head['x'], kp_head['y'], VIDEO_WIDTH, VIDEO_HEIGHT, SCALE_FACTOR)

            # Convertir en espace local de l'os
            local_pos = arm_obj.matrix_world.inverted() @ pos
            pbone.location = local_pos
            pbone.keyframe_insert(data_path='location', frame=blender_frame)

        # Affichage de progression
        if frame_idx % 30 == 0:
            print(f"  Frame {frame_idx}/{n_frames} ({int(frame_idx/n_frames*100)}%)")

    bpy.ops.object.mode_set(mode='OBJECT')
    scene.frame_set(1)
    print("✓ Animation terminée !")


# ═══════════════════════════════════════════════════════════════
# POINT D'ENTRÉE PRINCIPAL
# ═══════════════════════════════════════════════════════════════

def main():
    print("\n" + "═"*50)
    print("  MoCap Studio → Blender Importer")
    print("═"*50)

    scene = bpy.context.scene

    # 1. Charger le JSON
    data = load_json(JSON_FILE_PATH)

    # Récupérer les dimensions vidéo depuis les métadonnées si disponibles
    global VIDEO_WIDTH, VIDEO_HEIGHT
    meta = data.get('meta', {})
    res  = meta.get('resolution', {})
    if res:
        VIDEO_WIDTH  = res.get('width',  VIDEO_WIDTH)
        VIDEO_HEIGHT = res.get('height', VIDEO_HEIGHT)
        print(f"✓ Résolution détectée : {VIDEO_WIDTH}×{VIDEO_HEIGHT}")

    frames = data['frames']
    if not frames:
        raise ValueError("Aucune frame dans le fichier JSON.")

    # 2. Index du premier frame (pour créer le squelette en T-pose initiale)
    first_kps = build_keypoint_index(frames[0])

    # ── MÉTHODE A : Armature animée ─────────────────────────────
    print("\n[Méthode A] Création de l'armature...")
    arm_obj, arm_data = create_armature(ARMATURE_NAME)
    add_bones(arm_obj, arm_data, first_kps)
    animate_armature(arm_obj, data, scene)

    # ── MÉTHODE B : Empties (points de suivi bruts) ─────────────
    print("\n[Méthode B] Création des Empties (points de suivi)...")
    empties = create_keypoints_as_empties(data, scene)

    # 3. Zoomer la vue 3D sur l'armature
    try:
        for area in bpy.context.screen.areas:
            if area.type == 'VIEW_3D':
                with bpy.context.temp_override(area=area):
                    bpy.ops.view3d.view_all()
                break
    except Exception:
        pass  # Non bloquant

    print("\n" + "═"*50)
    print("✅  Import terminé avec succès !")
    print(f"   Armature : '{ARMATURE_NAME}' ({len(frames)} frames)")
    print(f"   Empties  : collection 'MoCap_Keypoints'")
    print("   → Appuyez sur ESPACE pour voir l'animation")
    print("═"*50 + "\n")


# Lancement
main()
