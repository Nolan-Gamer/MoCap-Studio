# ═══════════════════════════════════════════════════════════════════════════════
#  MoCap Studio — Blender Addon
#  Auteur  : MoCap Studio
#  Version : 1.2.0
#  Blender : 3.0 → 4.x
#
#  INSTALLATION :
#   1. Blender → Edit > Preferences > Add-ons > Install
#   2. Sélectionner ce fichier .py
#   3. Cocher la case pour l'activer
#   4. Panneau disponible dans : Vue 3D → N (sidebar) → onglet "MoCap"
# ═══════════════════════════════════════════════════════════════════════════════

bl_info = {
    "name":        "MoCap Studio Importer",
    "author":      "MoCap Studio",
    "version":     (1, 2, 0),
    "blender":     (3, 0, 0),
    "location":    "Vue 3D > Sidebar (N) > MoCap",
    "description": "Importe les fichiers JSON de MoCap Studio et applique l'animation sur une armature",
    "category":    "Animation",
    "doc_url":     "",
    "tracker_url": "",
}

import bpy
import json
import os
import math
from mathutils import Vector, Matrix, Euler
from bpy.props import (
    StringProperty, FloatProperty, IntProperty, BoolProperty,
    EnumProperty, CollectionProperty, PointerProperty
)
from bpy.types import Panel, Operator, PropertyGroup, AddonPreferences


# ═══════════════════════════════════════════════════════════════════════════════
#  CONSTANTES
# ═══════════════════════════════════════════════════════════════════════════════

KEYPOINT_NAMES = [
    'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
    'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
    'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
    'left_knee', 'right_knee', 'left_ankle', 'right_ankle',
]

# Labels lisibles pour l'UI
KEYPOINT_LABELS = {
    'nose':           "Nez",
    'left_eye':       "Œil G.",
    'right_eye':      "Œil D.",
    'left_ear':       "Oreille G.",
    'right_ear':      "Oreille D.",
    'left_shoulder':  "Épaule G.",
    'right_shoulder': "Épaule D.",
    'left_elbow':     "Coude G.",
    'right_elbow':    "Coude D.",
    'left_wrist':     "Poignet G.",
    'right_wrist':    "Poignet D.",
    'left_hip':       "Hanche G.",
    'right_hip':      "Hanche D.",
    'left_knee':      "Genou G.",
    'right_knee':     "Genou D.",
    'left_ankle':     "Cheville G.",
    'right_ankle':    "Cheville D.",
}

# Présets de mapping keypoint → nom d'os selon le type d'armature
BONE_PRESETS = {
    'RIGIFY': {
        'nose':           'face',
        'left_eye':       'eye.L',
        'right_eye':      'eye.R',
        'left_ear':       'ear.L',
        'right_ear':      'ear.R',
        'left_shoulder':  'upper_arm.L',
        'right_shoulder': 'upper_arm.R',
        'left_elbow':     'forearm.L',
        'right_elbow':    'forearm.R',
        'left_wrist':     'hand.L',
        'right_wrist':    'hand.R',
        'left_hip':       'thigh.L',
        'right_hip':      'thigh.R',
        'left_knee':      'shin.L',
        'right_knee':     'shin.R',
        'left_ankle':     'foot.L',
        'right_ankle':    'foot.R',
    },
    'MIXAMO': {
        'nose':           'Head',
        'left_eye':       'Head',
        'right_eye':      'Head',
        'left_ear':       'Head',
        'right_ear':      'Head',
        'left_shoulder':  'LeftArm',
        'right_shoulder': 'RightArm',
        'left_elbow':     'LeftForeArm',
        'right_elbow':    'RightForeArm',
        'left_wrist':     'LeftHand',
        'right_wrist':    'RightHand',
        'left_hip':       'LeftUpLeg',
        'right_hip':      'RightUpLeg',
        'left_knee':      'LeftLeg',
        'right_knee':     'RightLeg',
        'left_ankle':     'LeftFoot',
        'right_ankle':    'RightFoot',
    },
    'METARIG': {
        'nose':           'head',
        'left_eye':       'head',
        'right_eye':      'head',
        'left_ear':       'head',
        'right_ear':      'head',
        'left_shoulder':  'upper_arm.L',
        'right_shoulder': 'upper_arm.R',
        'left_elbow':     'forearm.L',
        'right_elbow':    'forearm.R',
        'left_wrist':     'hand.L',
        'right_wrist':    'hand.R',
        'left_hip':       'thigh.L',
        'right_hip':      'thigh.R',
        'left_knee':      'shin.L',
        'right_knee':     'shin.R',
        'left_ankle':     'foot.L',
        'right_ankle':    'foot.R',
    },
    'EMPTIES': {kp: '' for kp in KEYPOINT_NAMES},  # Mode Empties : pas de bones
}

# Connexions squelette pour la prévisualisation et l'armature auto
SKELETON_CONNECTIONS = [
    ('nose',          'left_eye'),
    ('nose',          'right_eye'),
    ('left_eye',      'left_ear'),
    ('right_eye',     'right_ear'),
    ('left_shoulder', 'right_shoulder'),
    ('left_shoulder', 'left_elbow'),
    ('left_elbow',    'left_wrist'),
    ('right_shoulder','right_elbow'),
    ('right_elbow',   'right_wrist'),
    ('left_shoulder', 'left_hip'),
    ('right_shoulder','right_hip'),
    ('left_hip',      'right_hip'),
    ('left_hip',      'left_knee'),
    ('left_knee',     'left_ankle'),
    ('right_hip',     'right_knee'),
    ('right_knee',    'right_ankle'),
]


# ═══════════════════════════════════════════════════════════════════════════════
#  PROPERTY GROUPS (données stockées dans la scène Blender)
# ═══════════════════════════════════════════════════════════════════════════════

class MOCAP_BoneMappingItem(PropertyGroup):
    """Une entrée du mapping : keypoint_name → bone_name"""
    keypoint: StringProperty(name="Keypoint", default="")
    bone:     StringProperty(name="Os",       default="")


class MOCAP_Settings(PropertyGroup):
    """Toutes les propriétés de l'addon stockées dans la scène."""

    # ── Fichier JSON ───────────────────────────────────────────────────────────
    json_filepath: StringProperty(
        name        = "Fichier JSON",
        description = "Chemin vers le fichier JSON exporté par MoCap Studio",
        default     = "",
        subtype     = 'FILE_PATH',
        update      = lambda self, ctx: MOCAP_OT_AnalyzeFile.run_analyze(ctx),
    )

    # ── Info fichier (lecture seule, remplies après analyse) ───────────────────
    file_frames:   IntProperty(name="Frames",   default=0)
    file_duration: FloatProperty(name="Durée",  default=0.0)
    file_model:    StringProperty(name="Modèle",default="")
    file_res_w:    IntProperty(name="Largeur",  default=1280)
    file_res_h:    IntProperty(name="Hauteur",  default=720)
    file_valid:    BoolProperty(name="Valide",  default=False)

    # ── Armature cible ─────────────────────────────────────────────────────────
    target_armature: PointerProperty(
        name        = "Armature cible",
        description = "L'armature sur laquelle appliquer l'animation",
        type        = bpy.types.Object,
        poll        = lambda self, obj: obj.type == 'ARMATURE',
    )

    # ── Préset de mapping ──────────────────────────────────────────────────────
    bone_preset: EnumProperty(
        name        = "Préset armature",
        description = "Nommage des os selon le type d'armature",
        items       = [
            ('RIGIFY',  "Rigify",       "Armature générée par Rigify"),
            ('MIXAMO',  "Mixamo",       "Armature importée depuis Mixamo/Adobe"),
            ('METARIG', "Meta-Rig",     "Meta-Rig Blender standard"),
            ('CUSTOM',  "Personnalisé", "Mapping manuel os par os"),
            ('EMPTIES', "Empties only", "Créer des Empties sans armature"),
        ],
        default     = 'MIXAMO',
        update      = lambda self, ctx: MOCAP_OT_ApplyPreset.run_apply(ctx),
    )

    # ── Mapping bone (collection) ──────────────────────────────────────────────
    bone_mapping:     CollectionProperty(type=MOCAP_BoneMappingItem)
    bone_mapping_idx: IntProperty(default=0)

    # ── Paramètres d'import ────────────────────────────────────────────────────
    scale_factor: FloatProperty(
        name        = "Échelle",
        description = "Facteur de mise à l'échelle (pixels → unités Blender)",
        default     = 0.005,
        min         = 0.0001,
        max         = 1.0,
        precision   = 4,
    )
    target_fps: IntProperty(
        name        = "FPS cible",
        description = "Fréquence d'image de l'animation Blender",
        default     = 30,
        min         = 1,
        max         = 120,
    )
    confidence_min: FloatProperty(
        name        = "Confiance min.",
        description = "Score minimum pour considérer un keypoint valide",
        default     = 0.30,
        min         = 0.0,
        max         = 1.0,
        precision   = 2,
        subtype     = 'FACTOR',
    )
    start_frame: IntProperty(
        name        = "Frame de départ",
        description = "Frame Blender à partir de laquelle démarrer l'animation",
        default     = 1,
        min         = 0,
    )
    use_loc: BoolProperty(
        name    = "Location",
        description = "Animer la position des os",
        default = True,
    )
    use_rot: BoolProperty(
        name    = "Rotation",
        description = "Calculer et animer la rotation des os (expérimental)",
        default = False,
    )
    smooth_keyframes: BoolProperty(
        name    = "Lisser les keyframes",
        description = "Appliquer un lissage Bezier sur les courbes F-Curve",
        default = True,
    )
    create_empties: BoolProperty(
        name    = "Créer les Empties",
        description = "Créer aussi des Empties pour les keypoints bruts",
        default = False,
    )
    clear_existing: BoolProperty(
        name    = "Effacer l'animation existante",
        description = "Supprimer les keyframes existants avant d'importer",
        default = True,
    )
    show_mapping: BoolProperty(
        name    = "Afficher le mapping",
        description = "Déplier la section de mapping des os",
        default = False,
    )

    # ── Progression ────────────────────────────────────────────────────────────
    progress:      FloatProperty(name="Progression", default=0.0, min=0.0, max=100.0)
    status_msg:    StringProperty(name="Statut", default="Prêt")
    import_done:   BoolProperty(default=False)


# ═══════════════════════════════════════════════════════════════════════════════
#  UTILITAIRES
# ═══════════════════════════════════════════════════════════════════════════════

def px_to_blender(x, y, w, h, scale):
    """Convertit des coordonnées pixel en espace Blender (Z=haut)."""
    bx =  (x - w / 2) * scale
    bz = -(y - h / 2) * scale   # Y pixel inversé → Z Blender
    by = 0.0
    return Vector((bx, by, bz))


def load_json_file(filepath):
    """Charge et valide le JSON. Retourne (data, error_msg)."""
    if not filepath:
        return None, "Aucun fichier sélectionné."
    if not os.path.exists(filepath):
        return None, f"Fichier introuvable : {filepath}"
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        return None, f"JSON invalide : {e}"

    if 'frames' not in data or not isinstance(data['frames'], list):
        return None, "Clé 'frames' manquante ou invalide."
    if len(data['frames']) == 0:
        return None, "Aucune frame dans le fichier."

    return data, None


def get_keypoint(frame, name, conf_min):
    """Retourne le keypoint si valide, sinon None."""
    for kp in frame.get('keypoints', []):
        if kp['name'] == name and kp.get('score', 0) >= conf_min:
            return kp
    return None


def get_mapping_dict(settings):
    """Retourne le dict {keypoint_name: bone_name} depuis la collection."""
    return {item.keypoint: item.bone for item in settings.bone_mapping if item.bone}


def ensure_bone_mapping_initialized(settings):
    """Initialise la collection bone_mapping si vide."""
    if len(settings.bone_mapping) == 0:
        for kp in KEYPOINT_NAMES:
            item = settings.bone_mapping.add()
            item.keypoint = kp
            item.bone = ""


# ═══════════════════════════════════════════════════════════════════════════════
#  OPERATORS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Analyser le fichier JSON ────────────────────────────────────────────────
class MOCAP_OT_AnalyzeFile(Operator):
    bl_idname      = "mocap.analyze_file"
    bl_label       = "Analyser le fichier"
    bl_description = "Lire les métadonnées du fichier JSON sélectionné"

    @staticmethod
    def run_analyze(context):
        """Peut être appelé depuis le update callback de json_filepath."""
        s = context.scene.mocap_settings
        data, err = load_json_file(bpy.path.abspath(s.json_filepath))
        if err:
            s.file_valid    = False
            s.status_msg    = f"❌ {err}"
            s.file_frames   = 0
            s.file_duration = 0.0
            s.file_model    = ""
            return

        meta = data.get('meta', {})
        res  = meta.get('resolution', {})
        s.file_frames   = len(data['frames'])
        s.file_duration = round(float(meta.get('duration', 0)), 2)
        s.file_model    = meta.get('model', 'inconnu')
        s.file_res_w    = int(res.get('width',  1280))
        s.file_res_h    = int(res.get('height', 720))
        s.file_valid    = True
        s.status_msg    = f"✓ {s.file_frames} frames — {s.file_duration}s"

    def execute(self, context):
        self.run_analyze(context)
        return {'FINISHED'}


# ── Appliquer un préset de mapping ─────────────────────────────────────────
class MOCAP_OT_ApplyPreset(Operator):
    bl_idname      = "mocap.apply_preset"
    bl_label       = "Appliquer le préset"
    bl_description = "Remplir automatiquement le mapping avec le préset sélectionné"

    @staticmethod
    def run_apply(context):
        s = context.scene.mocap_settings
        ensure_bone_mapping_initialized(s)
        preset = BONE_PRESETS.get(s.bone_preset, {})
        for item in s.bone_mapping:
            item.bone = preset.get(item.keypoint, "")

    def execute(self, context):
        self.run_apply(context)
        self.report({'INFO'}, f"Préset {context.scene.mocap_settings.bone_preset} appliqué")
        return {'FINISHED'}


# ── Détecter les os automatiquement depuis l'armature ──────────────────────
class MOCAP_OT_AutoDetectBones(Operator):
    bl_idname      = "mocap.auto_detect_bones"
    bl_label       = "Auto-détecter les os"
    bl_description = "Chercher automatiquement les os correspondants dans l'armature sélectionnée"

    def execute(self, context):
        s = context.scene.mocap_settings

        if not s.target_armature:
            self.report({'WARNING'}, "Sélectionnez d'abord une armature cible.")
            return {'CANCELLED'}

        arm = s.target_armature.data
        bone_names_lower = {b.name.lower(): b.name for b in arm.bones}

        ensure_bone_mapping_initialized(s)

        # Mots-clés à chercher par keypoint
        keywords = {
            'nose':           ['head', 'nose', 'neck'],
            'left_eye':       ['eye.l', 'eyelid.l', 'eye_l'],
            'right_eye':      ['eye.r', 'eyelid.r', 'eye_r'],
            'left_ear':       ['ear.l', 'ear_l'],
            'right_ear':      ['ear.r', 'ear_r'],
            'left_shoulder':  ['upper_arm.l', 'leftarm', 'arm.l', 'shoulder.l', 'clavicle.l'],
            'right_shoulder': ['upper_arm.r', 'rightarm', 'arm.r', 'shoulder.r', 'clavicle.r'],
            'left_elbow':     ['forearm.l', 'leftforearm', 'elbow.l', 'lowerarm.l'],
            'right_elbow':    ['forearm.r', 'rightforearm', 'elbow.r', 'lowerarm.r'],
            'left_wrist':     ['hand.l', 'lefthand', 'wrist.l', 'palm.l'],
            'right_wrist':    ['hand.r', 'righthand', 'wrist.r', 'palm.r'],
            'left_hip':       ['thigh.l', 'leftupleg', 'hip.l', 'pelvis.l', 'upleg.l'],
            'right_hip':      ['thigh.r', 'rightupleg', 'hip.r', 'pelvis.r', 'upleg.r'],
            'left_knee':      ['shin.l', 'leftleg', 'knee.l', 'leg.l', 'lowerleg.l'],
            'right_knee':     ['shin.r', 'rightleg', 'knee.r', 'leg.r', 'lowerleg.r'],
            'left_ankle':     ['foot.l', 'leftfoot', 'ankle.l', 'feet.l'],
            'right_ankle':    ['foot.r', 'rightfoot', 'ankle.r', 'feet.r'],
        }

        matched = 0
        for item in s.bone_mapping:
            kws = keywords.get(item.keypoint, [])
            found = ""
            for kw in kws:
                if kw in bone_names_lower:
                    found = bone_names_lower[kw]
                    break
            if found:
                item.bone = found
                matched += 1

        self.report({'INFO'}, f"Auto-détection : {matched}/{len(KEYPOINT_NAMES)} os trouvés")
        return {'FINISHED'}


# ── Vider le mapping ────────────────────────────────────────────────────────
class MOCAP_OT_ClearMapping(Operator):
    bl_idname      = "mocap.clear_mapping"
    bl_label       = "Vider le mapping"
    bl_description = "Effacer tous les noms d'os du mapping"

    def execute(self, context):
        for item in context.scene.mocap_settings.bone_mapping:
            item.bone = ""
        return {'FINISHED'}


# ── Importer l'animation ────────────────────────────────────────────────────
class MOCAP_OT_Import(Operator):
    bl_idname      = "mocap.import"
    bl_label       = "Importer l'animation"
    bl_description = "Lire le JSON et créer les keyframes sur l'armature cible"

    def execute(self, context):
        s = context.scene.mocap_settings
        scene = context.scene

        # ── Validation ─────────────────────────────────────────────────────
        filepath = bpy.path.abspath(s.json_filepath)
        data, err = load_json_file(filepath)
        if err:
            self.report({'ERROR'}, err)
            return {'CANCELLED'}

        use_empties = (s.bone_preset == 'EMPTIES')
        if not use_empties and not s.target_armature:
            self.report({'ERROR'}, "Sélectionnez une armature cible (ou passez en mode Empties).")
            return {'CANCELLED'}

        mapping = get_mapping_dict(s)
        if not use_empties and not any(mapping.values()):
            self.report({'ERROR'}, "Le mapping est vide. Appliquez un préset ou remplissez manuellement.")
            return {'CANCELLED'}

        # ── Récupération des paramètres ────────────────────────────────────
        frames      = data['frames']
        meta        = data.get('meta', {})
        res         = meta.get('resolution', {})
        vid_w       = int(res.get('width',  s.file_res_w or 1280))
        vid_h       = int(res.get('height', s.file_res_h or 720))
        scale       = s.scale_factor
        conf_min    = s.confidence_min
        start_f     = s.start_frame
        target_fps  = s.target_fps
        n_frames    = len(frames)

        self.report({'INFO'}, f"Import : {n_frames} frames, résolution {vid_w}×{vid_h}")

        # ── Configurer la timeline ────────────────────────────────────────
        scene.render.fps = target_fps
        scene.frame_start = start_f
        scene.frame_end   = start_f + n_frames - 1

        # ── Mode Empties uniquement ───────────────────────────────────────
        if use_empties or s.create_empties:
            self._create_empties_animation(context, frames, vid_w, vid_h, scale, conf_min, start_f)
            if use_empties:
                s.status_msg  = f"✅ {n_frames} frames importées (Empties)"
                s.import_done = True
                return {'FINISHED'}

        # ── Mode Armature ─────────────────────────────────────────────────
        arm_obj = s.target_armature
        arm     = arm_obj.data

        # Vérifier que les os du mapping existent dans l'armature
        missing_bones = []
        for kp, bone_name in mapping.items():
            if bone_name and bone_name not in arm.bones:
                missing_bones.append(f"{kp} → '{bone_name}'")

        if missing_bones:
            self.report({'WARNING'},
                f"Os introuvables dans l'armature : {', '.join(missing_bones[:3])}{'…' if len(missing_bones)>3 else ''}"
            )

        # Effacer l'animation existante si demandé
        if s.clear_existing and arm_obj.animation_data:
            arm_obj.animation_data.action = None

        # Créer l'action
        action_name = f"MoCap_{os.path.basename(filepath)}"
        action = bpy.data.actions.new(name=action_name)
        if not arm_obj.animation_data:
            arm_obj.animation_data_create()
        arm_obj.animation_data.action = action

        # ── Boucle principale : keyframe par keyframe ─────────────────────
        bpy.context.view_layer.objects.active = arm_obj
        bpy.ops.object.mode_set(mode='POSE')

        pose_bones = arm_obj.pose.bones
        kf_inserted = 0

        for frame_idx, frame in enumerate(frames):
            blender_frame = start_f + frame_idx

            # Matrice monde inverse de l'armature (pour espace local)
            arm_inv = arm_obj.matrix_world.inverted()

            for kp_name in KEYPOINT_NAMES:
                bone_name = mapping.get(kp_name, "")
                if not bone_name:
                    continue
                if bone_name not in pose_bones:
                    continue

                kp = get_keypoint(frame, kp_name, conf_min)
                if not kp:
                    continue

                pbone = pose_bones[bone_name]

                # Convertir position pixel → espace monde → espace local os
                world_pos = px_to_blender(kp['x'], kp['y'], vid_w, vid_h, scale)
                local_pos = arm_inv @ world_pos

                # Appliquer via la matrice de l'os en pose (sans écraser la rotation)
                pbone.location = local_pos

                # Insérer le keyframe de location
                if s.use_loc:
                    pbone.keyframe_insert(
                        data_path = 'location',
                        frame     = blender_frame,
                        group     = kp_name,
                    )
                    kf_inserted += 1

        bpy.ops.object.mode_set(mode='OBJECT')

        # ── Lissage des courbes (Bezier) ───────────────────────────────────
        if s.smooth_keyframes and action:
            for fcurve in action.fcurves:
                for kfp in fcurve.keyframe_points:
                    kfp.interpolation = 'BEZIER'
                    kfp.handle_left_type  = 'AUTO_CLAMPED'
                    kfp.handle_right_type = 'AUTO_CLAMPED'
            self.report({'INFO'}, "Keyframes lissés (Bezier)")

        # ── Résultat ───────────────────────────────────────────────────────
        scene.frame_set(start_f)
        s.status_msg  = f"✅ {kf_inserted} keyframes — action '{action_name}'"
        s.import_done = True
        self.report({'INFO'}, s.status_msg)
        return {'FINISHED'}

    # ── Créer les Empties animés ──────────────────────────────────────────────
    def _create_empties_animation(self, context, frames, vid_w, vid_h, scale, conf_min, start_f):
        scene   = context.scene
        s       = scene.mocap_settings

        # Collection dédiée
        coll_name = "MoCap_Keypoints"
        if coll_name in bpy.data.collections:
            old = bpy.data.collections[coll_name]
            for obj in list(old.objects):
                bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.collections.remove(old)

        coll = bpy.data.collections.new(coll_name)
        scene.collection.children.link(coll)

        # Créer un Empty par keypoint
        empties = {}
        for kp_name in KEYPOINT_NAMES:
            empty = bpy.data.objects.new(f"KP_{kp_name}", None)
            empty.empty_display_type = 'SPHERE'
            empty.empty_display_size = 0.04
            coll.objects.link(empty)
            empties[kp_name] = empty

        # Animer
        for frame_idx, frame in enumerate(frames):
            bf = start_f + frame_idx
            for kp_name, empty in empties.items():
                kp = get_keypoint(frame, kp_name, conf_min)
                if not kp:
                    continue
                empty.location = px_to_blender(kp['x'], kp['y'], vid_w, vid_h, scale)
                empty.keyframe_insert(data_path='location', frame=bf)

        self.report({'INFO'}, f"Empties créés dans la collection '{coll_name}'")


# ── Effacer l'animation importée ────────────────────────────────────────────
class MOCAP_OT_ClearAnimation(Operator):
    bl_idname      = "mocap.clear_animation"
    bl_label       = "Effacer l'animation"
    bl_description = "Supprimer l'action MoCap de l'armature cible"

    def execute(self, context):
        s = context.scene.mocap_settings
        if s.target_armature and s.target_armature.animation_data:
            action = s.target_armature.animation_data.action
            if action and 'MoCap_' in action.name:
                bpy.data.actions.remove(action)
                s.status_msg = "Action MoCap supprimée."
            else:
                s.target_armature.animation_data.action = None
                s.status_msg = "Animation désassignée."
        s.import_done = False
        return {'FINISHED'}


# ── Prévisualiser en mode filaire ────────────────────────────────────────────
class MOCAP_OT_Preview(Operator):
    bl_idname      = "mocap.preview"
    bl_label       = "Prévisualiser (frame 1)"
    bl_description = "Aller à la frame de départ et jouer l'animation"

    def execute(self, context):
        s = context.scene.mocap_settings
        context.scene.frame_set(s.start_frame)
        bpy.ops.screen.animation_play()
        return {'FINISHED'}


# ── Sélectionner l'armature active ──────────────────────────────────────────
class MOCAP_OT_UseActiveArmature(Operator):
    bl_idname      = "mocap.use_active_armature"
    bl_label       = "Utiliser l'armature active"
    bl_description = "Utiliser l'objet sélectionné dans la scène comme armature cible"

    def execute(self, context):
        obj = context.active_object
        if obj and obj.type == 'ARMATURE':
            context.scene.mocap_settings.target_armature = obj
            self.report({'INFO'}, f"Armature '{obj.name}' sélectionnée")
        else:
            self.report({'WARNING'}, "L'objet actif n'est pas une armature.")
        return {'FINISHED'}


# ═══════════════════════════════════════════════════════════════════════════════
#  PANELS (interface N-panel)
# ═══════════════════════════════════════════════════════════════════════════════

class MOCAP_PT_Base:
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = 'MoCap'


class MOCAP_PT_Main(MOCAP_PT_Base, Panel):
    bl_idname = "MOCAP_PT_Main"
    bl_label  = "MoCap Studio Importer"

    def draw_header(self, context):
        self.layout.label(text="", icon='ARMATURE_DATA')

    def draw(self, context):
        layout = self.layout
        s = context.scene.mocap_settings

        # Statut général
        box = layout.box()
        row = box.row()
        if s.file_valid:
            row.label(text=s.status_msg, icon='CHECKMARK')
        elif s.status_msg.startswith("❌"):
            row.label(text=s.status_msg, icon='ERROR')
        else:
            row.label(text=s.status_msg, icon='INFO')


class MOCAP_PT_FileSection(MOCAP_PT_Base, Panel):
    bl_idname = "MOCAP_PT_FileSection"
    bl_label  = "① Fichier JSON"
    bl_parent_id = "MOCAP_PT_Main"

    def draw(self, context):
        layout = self.layout
        s = context.scene.mocap_settings

        layout.prop(s, "json_filepath", text="")
        layout.operator("mocap.analyze_file", icon='FILE_REFRESH')

        # Infos fichier
        if s.file_valid:
            col = layout.column(align=True)
            col.scale_y = 0.85
            row = col.row()
            row.label(text=f"Frames :  {s.file_frames}", icon='RENDER_ANIMATION')
            row = col.row()
            row.label(text=f"Durée :   {s.file_duration} s", icon='TIME')
            row = col.row()
            row.label(text=f"Modèle :  {s.file_model}", icon='PHYSICS')
            row = col.row()
            row.label(text=f"Résol. : {s.file_res_w}×{s.file_res_h}", icon='RESTRICT_VIEW_OFF')


class MOCAP_PT_ArmatureSection(MOCAP_PT_Base, Panel):
    bl_idname    = "MOCAP_PT_ArmatureSection"
    bl_label     = "② Armature cible"
    bl_parent_id = "MOCAP_PT_Main"

    def draw(self, context):
        layout = self.layout
        s = context.scene.mocap_settings

        row = layout.row(align=True)
        row.prop(s, "target_armature", text="")
        row.operator("mocap.use_active_armature", text="", icon='EYEDROPPER')

        if s.target_armature:
            arm = s.target_armature.data
            layout.label(
                text=f"{len(arm.bones)} os dans '{s.target_armature.name}'",
                icon='BONE_DATA'
            )


class MOCAP_PT_MappingSection(MOCAP_PT_Base, Panel):
    bl_idname    = "MOCAP_PT_MappingSection"
    bl_label     = "③ Mapping des os"
    bl_parent_id = "MOCAP_PT_Main"

    def draw(self, context):
        layout = self.layout
        s = context.scene.mocap_settings

        # Préset
        row = layout.row(align=True)
        row.prop(s, "bone_preset", text="Préset")
        row.operator("mocap.apply_preset", text="", icon='FILE_REFRESH')

        if s.bone_preset == 'EMPTIES':
            layout.label(text="Mode Empties : pas de mapping nécessaire", icon='INFO')
            return

        # Boutons d'aide
        row = layout.row(align=True)
        row.operator("mocap.auto_detect_bones", icon='ZOOM_ALL')
        row.operator("mocap.clear_mapping", icon='X')

        # Toggle pour afficher/cacher le mapping détaillé
        layout.prop(s, "show_mapping",
                    text="Afficher le mapping détaillé",
                    icon='TRIA_DOWN' if s.show_mapping else 'TRIA_RIGHT',
                    emboss=False)

        if not s.show_mapping:
            # Résumé compact
            ensure_bone_mapping_initialized(s)
            filled = sum(1 for item in s.bone_mapping if item.bone)
            layout.label(
                text=f"{filled}/{len(KEYPOINT_NAMES)} os mappés",
                icon='CHECKMARK' if filled == len(KEYPOINT_NAMES) else 'ERROR'
            )
            return

        # Mapping complet keypoint par keypoint
        ensure_bone_mapping_initialized(s)
        col = layout.column(align=True)

        for item in s.bone_mapping:
            row = col.row(align=True)
            label = KEYPOINT_LABELS.get(item.keypoint, item.keypoint)
            row.label(text=label, icon='BONE_DATA')

            if s.target_armature:
                # Champ texte avec auto-complétion si armature disponible
                row.prop_search(item, "bone", s.target_armature.data, "bones", text="")
            else:
                row.prop(item, "bone", text="")


class MOCAP_PT_SettingsSection(MOCAP_PT_Base, Panel):
    bl_idname    = "MOCAP_PT_SettingsSection"
    bl_label     = "④ Paramètres"
    bl_parent_id = "MOCAP_PT_Main"
    bl_options   = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout = self.layout
        s = context.scene.mocap_settings

        col = layout.column(align=True)
        col.prop(s, "scale_factor",    slider=False)
        col.prop(s, "target_fps",      slider=False)
        col.prop(s, "confidence_min",  slider=True)
        col.prop(s, "start_frame",     slider=False)

        layout.separator()
        col = layout.column(align=True)
        col.label(text="Options :", icon='SETTINGS')
        col.prop(s, "use_loc")
        col.prop(s, "smooth_keyframes")
        col.prop(s, "create_empties")
        col.prop(s, "clear_existing")


class MOCAP_PT_ImportSection(MOCAP_PT_Base, Panel):
    bl_idname    = "MOCAP_PT_ImportSection"
    bl_label     = "⑤ Importer"
    bl_parent_id = "MOCAP_PT_Main"

    def draw(self, context):
        layout = self.layout
        s = context.scene.mocap_settings

        # Validation rapide
        can_import = s.file_valid and (s.target_armature or s.bone_preset == 'EMPTIES')

        col = layout.column(align=True)
        col.scale_y = 1.5
        row = col.row(align=True)
        row.enabled = can_import
        row.operator("mocap.import", text="▶ Importer l'animation", icon='IMPORT')

        if not s.file_valid:
            layout.label(text="Sélectionnez un fichier JSON valide", icon='ERROR')
        elif not s.target_armature and s.bone_preset != 'EMPTIES':
            layout.label(text="Sélectionnez une armature cible", icon='ERROR')

        layout.separator()
        row = layout.row(align=True)
        row.operator("mocap.preview",         text="▶ Play",      icon='PLAY')
        row.operator("mocap.clear_animation", text="🗑 Effacer",  icon='TRASH')


# ═══════════════════════════════════════════════════════════════════════════════
#  ENREGISTREMENT
# ═══════════════════════════════════════════════════════════════════════════════

CLASSES = [
    # Property groups
    MOCAP_BoneMappingItem,
    MOCAP_Settings,
    # Operators
    MOCAP_OT_AnalyzeFile,
    MOCAP_OT_ApplyPreset,
    MOCAP_OT_AutoDetectBones,
    MOCAP_OT_ClearMapping,
    MOCAP_OT_Import,
    MOCAP_OT_ClearAnimation,
    MOCAP_OT_Preview,
    MOCAP_OT_UseActiveArmature,
    # Panels
    MOCAP_PT_Main,
    MOCAP_PT_FileSection,
    MOCAP_PT_ArmatureSection,
    MOCAP_PT_MappingSection,
    MOCAP_PT_SettingsSection,
    MOCAP_PT_ImportSection,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    bpy.types.Scene.mocap_settings = PointerProperty(type=MOCAP_Settings)
    print("[MoCap Studio] Addon enregistré ✓")


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
    del bpy.types.Scene.mocap_settings
    print("[MoCap Studio] Addon désinstallé")


if __name__ == "__main__":
    register()
