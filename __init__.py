import importlib
from distutils.version import StrictVersion as Version
import json
import os
import time
from itertools import chain

import numpy as np
import mathutils
import bpy
from bpy.props import (
    BoolProperty,
    CollectionProperty,
    EnumProperty,
    PointerProperty,
    StringProperty
)
from bpy_extras.io_utils import (
    ExportHelper,
    orientation_helper_factory,
    axis_conversion,
)

from .blendergltf import export_gltf
from .filters import visible_only, selected_only, used_only
from . import extension_exporters
from .pbr_utils import PbrExportPanel, PbrSettings


bl_info = {
    "name": "glTF format",
    "author": "Daniel Stokes and GitHub contributors",
    "version": (1, 1, 0),
    "blender": (2, 76, 0),
    "location": "File > Import-Export",
    "description": "Export glTF",
    "warning": "",
    "wiki_url": "https://github.com/Kupoman/blendergltf/blob/master/README.md"
                "",
    "tracker_url": "https://github.com/Kupoman/blendergltf/issues",
    "support": 'COMMUNITY',
    "category": "Import-Export"
}


if "bpy" in locals():
    importlib.reload(locals()['blendergltf'])
    importlib.reload(locals()['filters'])
    importlib.reload(locals()['extension_exporters'])
    importlib.reload(locals()['pbr_utils'])


GLTFOrientationHelper = orientation_helper_factory(
    "GLTFOrientationHelper", axis_forward='Z', axis_up='Y'
)

VERSION_ITEMS = (
    ('1.0', '1.0', ''),
    ('2.0', '2.0', ''),
)

PROFILE_ITEMS = (
    ('WEB', 'Web', 'Export shaders for WebGL 1.0 use (shader version 100)'),
    ('DESKTOP', 'Desktop', 'Export shaders for OpenGL 3.0 use (shader version 130)')
)
IMAGE_STORAGE_ITEMS = (
    ('EMBED', 'Embed', 'Embed image data into the glTF file'),
    ('REFERENCE', 'Reference', 'Use the same filepath that Blender uses for images'),
    ('COPY', 'Copy', 'Copy images to output directory and use a relative reference')
)
ANIM_EXPORT_ITEMS = (
    ('ACTIVE', 'Active Only', 'Export the active action per object'),
    ('ELIGIBLE', 'All Eligible', 'Export all actions that can be used by an object'),
)
_DEFAULT_VALUES_BY_PARAM_TYPE = {
    5124 : 1, # GL_INT
    5126 : 1.0, # GL_FLOAT
    35664: (1.0, 1.0), # GL_FLOAT_VEC2
    35665: (1.0, 1.0, 1.0), # GL_FLOAT_VEC3
    35666: (1.0, 1.0, 1.0, 1.0), # GL_FLOAT_VEC4
    35674: (1.0, 0.0, 0.0, 1.0), # GL_FLOAT_MAT2
    35675: (1.0, 0.0, 0.0,
            0.0, 1.0, 0.0,
            0.0, 0.0, 1.0), # GL_FLOAT_MAT3
    35676: (1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0), # GL_FLOAT_MAT4
}

class ExtPropertyGroup(bpy.types.PropertyGroup):
    name = StringProperty(name='Extension Name')
    enable = BoolProperty(
        name='Enable',
        description='Enable this extension',
        default=False
    )


class ExportGLTF(bpy.types.Operator, ExportHelper, GLTFOrientationHelper):
    """Save a Khronos glTF File"""
    bl_idname = 'export_scene.gltf'
    bl_label = 'Export glTF'
    bl_options = {'PRESET'}

    filename_ext = ''
    filter_glob = StringProperty(
        default='*.gltf;*.glb',
        options={'HIDDEN'},
    )

    # Override filepath to simplify linting
    filepath = StringProperty(
        name='File Path',
        description='Filepath used for exporting the file',
        maxlen=1024,
        subtype='FILE_PATH'
    )

    check_extension = True

    ext_exporters = sorted(
        [exporter() for exporter in extension_exporters.__all__],
        key=lambda ext: ext.ext_meta['name']
    )
    extension_props = CollectionProperty(
        name='Extensions',
        type=ExtPropertyGroup,
        description='Select extensions to enable'
    )
    ext_prop_to_exporter_map = {}
    for ext_exporter in ext_exporters:
        meta = ext_exporter.ext_meta
        if 'settings' in meta:
            name = 'settings_' + meta['name']
            prop_group = type(name, (bpy.types.PropertyGroup,), meta['settings'])
            bpy.utils.register_class(prop_group)
            value = PointerProperty(type=prop_group)
            locals()[name] = value

    # Dummy property to get icon with tooltip
    draft_prop = BoolProperty(
        name='',
        description='This extension is currently in a draft phase',
    )

    # blendergltf settings
    nodes_export_hidden = BoolProperty(
        name='Export Hidden Objects',
        description='Export nodes that are not set to visible',
        default=False
    )
    nodes_selected_only = BoolProperty(
        name='Selection Only',
        description='Only export nodes that are currently selected',
        default=False
    )
    materials_disable = BoolProperty(
        name='Disable Material Export',
        description='Export minimum default materials. Useful when using material extensions',
        default=False
    )
    meshes_apply_modifiers = BoolProperty(
        name='Apply Modifiers',
        description='Apply all modifiers to the output mesh data',
        default=True
    )
    meshes_interleave_vertex_data = BoolProperty(
        name='Interleave Vertex Data',
        description=(
            'Store data for each vertex contiguously'
            'instead of each vertex property (e.g. position) contiguously'
        ),
        default=False
    )
    animations_object_export = EnumProperty(
        items=ANIM_EXPORT_ITEMS,
        name='Objects',
        default='ACTIVE'
    )
    animations_armature_export = EnumProperty(
        items=ANIM_EXPORT_ITEMS,
        name='Armatures',
        default='ELIGIBLE'
    )
    images_data_storage = EnumProperty(
        items=IMAGE_STORAGE_ITEMS,
        name='Storage',
        default='COPY'
    )
    images_allow_srgb = BoolProperty(
        name='sRGB Texture Support',
        description='Use sRGB texture formats for sRGB textures',
        default=False
    )
    buffers_embed_data = BoolProperty(
        name='Embed Buffer Data',
        description='Embed buffer data into the glTF file',
        default=False
    )
    buffers_combine_data = BoolProperty(
        name='Combine Buffer Data',
        description='Combine all buffers into a single buffer',
        default=True
    )
    asset_version = EnumProperty(
        items=VERSION_ITEMS,
        name='Version',
        default='2.0'
    )
    asset_profile = EnumProperty(
        items=PROFILE_ITEMS,
        name='Profile',
        default='WEB'
    )
    gltf_export_binary = BoolProperty(
        name='Export as binary',
        description='Export to the binary glTF file format (.glb)',
        default=False
    )
    pretty_print = BoolProperty(
        name='Pretty-print / indent JSON',
        description='Export JSON with indentation and a newline',
        default=True
    )
    blocks_prune_unused = BoolProperty(
        name='Prune Unused Resources',
        description='Do not export any data-blocks that have no users or references',
        default=True
    )
    enable_actions = BoolProperty(
        name='Actions',
        description='Enable the export of actions',
        default=True
    )
    enable_cameras = BoolProperty(
        name='Cameras',
        description='Enable the export of cameras',
        default=True
    )
    enable_lamps = BoolProperty(
        name='Lamps',
        description='Enable the export of lamps',
        default=True
    )
    enable_materials = BoolProperty(
        name='Materials',
        description='Enable the export of materials',
        default=True
    )
    enable_meshes = BoolProperty(
        name='Meshes',
        description='Enable the export of meshes',
        default=True
    )
    enable_textures = BoolProperty(
        name='Textures',
        description='Enable the export of textures',
        default=True
    )

    def update_extensions(self):
        self.ext_prop_to_exporter_map = {ext.ext_meta['name']: ext for ext in self.ext_exporters}

        for exporter in self.ext_exporters:
            exporter.ext_meta['enable'] = False
        for prop in self.extension_props:
            exporter = self.ext_prop_to_exporter_map[prop.name]
            exporter.ext_meta['enable'] = prop.enable

        self.extension_props.clear()
        for exporter in self.ext_exporters:
            prop = self.extension_props.add()
            prop.name = exporter.ext_meta['name']
            prop.enable = exporter.ext_meta['enable']

            if exporter.ext_meta['name'] == 'KHR_technique_webgl':
                prop.enable = Version(self.asset_version) < Version('2.0')

    def invoke(self, context, event):
        self.update_extensions()
        return super().invoke(context, event)

    def check(self, context):
        redraw = False

        if self.gltf_export_binary and self.filepath.endswith('.gltf'):
            self.filepath = self.filepath[:-4] + 'glb'
            redraw = True
        elif not self.gltf_export_binary and self.filepath.endswith('.glb'):
            self.filepath = self.filepath[:-3] + 'gltf'
            redraw = True

        if self.gltf_export_binary and self.buffers_embed_data and not self.buffers_combine_data:
            self.buffers_combine_data = True
            redraw = True

        self.filename_ext = '.glb' if self.gltf_export_binary else '.gltf'
        redraw = redraw or super().check(context)

        return redraw

    def draw(self, context):
        self.update_extensions()
        layout = self.layout

        col = layout.box().column(align=True)
        col.label('Enable:')
        row = col.row(align=True)
        row.prop(self, 'enable_actions', toggle=True)
        row.prop(self, 'enable_cameras', toggle=True)
        row.prop(self, 'enable_lamps', toggle=True)
        row = col.row(align=True)
        row.prop(self, 'enable_materials', toggle=True)
        row.prop(self, 'enable_meshes', toggle=True)
        row.prop(self, 'enable_textures', toggle=True)

        col = layout.box().column()
        col.label('Axis Conversion:', icon='MANIPUL')
        col.prop(self, 'axis_up')
        col.prop(self, 'axis_forward')

        col = layout.box().column()
        col.label('Nodes:', icon='OBJECT_DATA')
        col.prop(self, 'nodes_export_hidden')
        col.prop(self, 'nodes_selected_only')

        col = layout.box().column()
        col.label('Meshes:', icon='MESH_DATA')
        col.prop(self, 'meshes_apply_modifiers')
        col.prop(self, 'meshes_interleave_vertex_data')

        col = layout.box().column()
        col.label('Materials:', icon='MATERIAL_DATA')
        col.prop(self, 'materials_disable')
        if Version(self.asset_version) < Version('2.0'):
            material_settings = getattr(self, 'settings_KHR_technique_webgl')
            col.prop(material_settings, 'embed_shaders')

        col = layout.box().column()
        col.label('Animations:', icon='ACTION')
        col.prop(self, 'animations_armature_export')
        col.prop(self, 'animations_object_export')

        col = layout.box().column()
        col.label('Images:', icon='IMAGE_DATA')
        col.prop(self, 'images_data_storage')
        if Version(self.asset_version) < Version('2.0'):
            col.prop(self, 'images_allow_srgb')

        col = layout.box().column()
        col.label('Buffers:', icon='SORTALPHA')
        col.prop(self, 'buffers_embed_data')

        col = col.column()
        col.enabled = not self.gltf_export_binary or not self.buffers_embed_data
        prop = col.prop(self, 'buffers_combine_data')

        col = layout.box().column()
        col.label('Extensions:', icon='PLUGIN')
        extension_filter = set()

        # Disable KHR_technique_webgl for all glTF versions
        extension_filter.add('KHR_technique_webgl')
        for i in range(len(self.extension_props)):
            prop = self.extension_props[i]
            extension_exporter = self.ext_prop_to_exporter_map[prop.name]

            if extension_exporter.ext_meta['name'] in extension_filter:
                continue

            row = col.row()
            row.prop(prop, 'enable', text=prop.name)
            if extension_exporter.ext_meta.get('isDraft', False):
                row.prop(self, 'draft_prop', icon='ERROR', emboss=False)
            info_op = row.operator('wm.url_open', icon='INFO', emboss=False)
            info_op.url = extension_exporter.ext_meta.get('url', '')

            if prop.enable:
                settings = getattr(self, 'settings_' + prop.name, None)
                if settings:
                    box = col.box()
                    if hasattr(extension_exporter, 'draw_settings'):
                        extension_exporter.draw_settings(box, settings, context)
                    else:
                        setting_props = [
                            name for name in dir(settings)
                            if not name.startswith('_')
                            and name not in ('bl_rna', 'name', 'rna_type')
                        ]
                        for setting_prop in setting_props:
                            box.prop(settings, setting_prop)
                    if i < len(self.extension_props) - 1:
                        col.separator()
                        col.separator()

        col = layout.box().column()
        col.label('Output:', icon='SCRIPTWIN')
        col.prop(self, 'gltf_export_binary')
        col.prop(self, 'asset_version')
        if Version(self.asset_version) < Version('2.0'):
            col.prop(self, 'asset_profile')
        col.prop(self, 'pretty_print')
        col.prop(self, 'blocks_prune_unused')

    def execute(self, _):
        # Copy properties to settings
        settings = self.as_keywords(ignore=(
            "filter_glob",
            "axis_up",
            "axis_forward",
        ))

        # Set the output directory based on the supplied file path
        settings['gltf_output_dir'] = os.path.dirname(self.filepath)

        # Set the output name
        settings['gltf_name'] = os.path.splitext(os.path.basename(self.filepath))[0]

        # Calculate a global transform matrix to apply to a root node
        settings['nodes_global_matrix'] = axis_conversion(
            to_forward=self.axis_forward,
            to_up=self.axis_up
        ).to_4x4()

        # filter data according to settings
        data = {
            'actions': list(bpy.data.actions) if self.enable_actions else [],
            'cameras': list(bpy.data.cameras) if self.enable_cameras else [],
            'lamps': list(bpy.data.lamps) if self.enable_lamps else [],
            'images': list(bpy.data.images) if self.enable_textures else [],
            'materials': list(bpy.data.materials) if self.enable_materials else [],
            'meshes': list(bpy.data.meshes) if self.enable_meshes else [],
            'objects': list(bpy.data.objects),
            'scenes': list(bpy.data.scenes),
            'textures': list(bpy.data.textures) if self.enable_textures else [],
        }

        # Remove objects that point to disabled data
        if not self.enable_cameras:
            data['objects'] = [
                obj for obj in data['objects']
                if not isinstance(obj.data, bpy.types.Camera)
            ]
        if not self.enable_lamps:
            data['objects'] = [
                obj for obj in data['objects']
                if not isinstance(obj.data, bpy.types.Lamp)
            ]
        if not self.enable_meshes:
            data['objects'] = [
                obj for obj in data['objects']
                if not isinstance(obj.data, bpy.types.Mesh)
            ]

        if not settings['nodes_export_hidden']:
            data = visible_only(data)

        if settings['nodes_selected_only']:
            data = selected_only(data)

        if settings['blocks_prune_unused']:
            data = used_only(data)

        for ext_exporter in self.ext_exporters:
            ext_exporter.settings = getattr(
                self,
                'settings_' + ext_exporter.ext_meta['name'],
                None
            )

        def is_builtin_mat_ext(prop_name):
            if Version(self.asset_version) < Version('2.0'):
                return prop_name == 'KHR_technique_webgl'
            return False

        settings['extension_exporters'] = [
            self.ext_prop_to_exporter_map[prop.name]
            for prop in self.extension_props
            if prop.enable and not (self.materials_disable and is_builtin_mat_ext(prop.name))
        ]

        start_time = time.perf_counter()
        gltf = export_gltf(data, settings)

        if settings['nodes_global_matrix'] != mathutils.Matrix.Identity(4):
            _matrix = np.array(list(chain.from_iterable([[v[0], v[1], v[2], v[3]]
                                                         for v in settings['nodes_global_matrix'][:]])), dtype=np.float32)
            # _matrix = list(chain.from_iterable([[v[0], v[1], v[2]]
            #                                    for v in settings['nodes_global_matrix'][:3]]))
            #matrix = np.eye(4, dtype=np.float32)
            #matrix[:3,:3] = np.array(_matrix).reshape(3,3)
            matrix = tuple(_matrix.ravel())
            # matrix = list(np.array(chain.from_iterable([[v[0], v[1], v[2], v[3]]
            #                                             for v in settings['nodes_global_matrix'][:]])).reshape(4,4).T.ravel())
            print(matrix)
            for scene_id, scene in gltf['scenes'].items():
                root_node = {'children': scene['nodes'],
                             'matrix': matrix}
                root_node_id = '%s_root' % scene_id
                gltf['nodes'][root_node_id] = root_node
                scene['nodes'] = [root_node_id]

        if gltf['scenes']:
            gltf['scene'] = sorted(gltf['scenes'].keys())[0]

        for technique in gltf['techniques'].values():
            for parameter in technique['parameters'].values():
                if 'value' in parameter and parameter['value'] is None:
                    parameter['value'] = _DEFAULT_VALUES_BY_PARAM_TYPE[parameter['type']]
        end_time = time.perf_counter()
        print('Export took {:.4} seconds'.format(end_time - start_time))

        if self.gltf_export_binary:
            with open(self.filepath, 'wb') as fout:
                fout.write(gltf)
        else:
            with open(self.filepath + '.raw', 'w') as f:
                f.write('\n'.join('%s: %s' % (k, v) for k, v in gltf.items()))
            with open(self.filepath, 'w') as fout:
                # Figure out indentation
                indent = 4 if self.pretty_print else None

                # Dump the JSON

                json.dump(gltf, fout, indent=indent, sort_keys=True, check_circular=False)

                if self.pretty_print:
                    # Write a newline to the end of the file
                    fout.write('\n')
        return {'FINISHED'}


def menu_func_export(self, _):
    self.layout.operator(ExportGLTF.bl_idname, text="glTF (.gltf)")


def register():
    bpy.utils.register_module(__name__)

    bpy.types.Material.pbr_export_settings = bpy.props.PointerProperty(type=PbrSettings)

    bpy.types.INFO_MT_file_export.append(menu_func_export)


def unregister():
    bpy.utils.unregister_module(__name__)

    bpy.types.INFO_MT_file_export.remove(menu_func_export)
