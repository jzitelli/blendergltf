from distutils.version import StrictVersion as Version

import pytest


# pylint: disable=redefined-outer-name


@pytest.fixture
def blendergltf(mocker):
    # pylint: disable=protected-access
    import sys
    sys.modules['bpy'] = mocker.MagicMock()
    sys.modules['idprop'] = mocker.MagicMock()
    sys.modules['mathutils'] = mocker.MagicMock()

    import blendergltf as _blendergltf
    mocker.patch.object(_blendergltf, '_get_custom_properties')
    _blendergltf._get_custom_properties.return_value = {}
    return _blendergltf


@pytest.fixture
def state():
    from blendergltf import DEFAULT_SETTINGS as settings

    _state = {
        'version': Version(settings['asset_version']),
        'settings': settings,
        'animation_dt': 1.0 / 24.0,
        'mod_meshes': {},
        'shape_keys': {},
        'skinned_meshes': {},
        'dupli_nodes': [],
        'extensions_used': [],
        'gl_extensions_used': [],
        'buffers': [],
        'samplers': [],
        'input': {
            'buffers': [],
            'accessors': [],
            'bufferViews': [],
            'bones': [],
            'anim_samplers': [],
            'samplers': [],
            'skins': [],
            'dupli_ids': [],

            'actions': [],
            'cameras': [],
            'lamps': [],
            'images': [],
            'materials': [],
            'meshes': [],
            'objects': [],
            'scenes': [],
            'textures': [],
        },
        'output': {
            'extensions': [],
        },
        'references': [],
        'files': {},
    }

    return _state


@pytest.fixture
def bpy_camera_default(mocker):
    camera = mocker.MagicMock()

    camera.name = 'Camera'
    camera.type = 'PERSP'
    camera.angle_x = 0.8575560450553894
    camera.angle_y = 0.5033799409866333
    camera.clip_end = 100.0
    camera.clip_start = 0.10000000149011612
    camera.ortho_scale = 7.314285755157471

    return camera


@pytest.fixture
def gltf_camera_default():
    return {
        'name': 'Camera',
        'perspective': {
            'aspectRatio': 1.703595982340029,
            'yfov': 0.5033799409866333,
            'zfar': 100.0,
            'znear': 0.10000000149011612
        },
        'type': 'perspective'
    }


@pytest.fixture
def bpy_material_default(mocker):
    material = mocker.MagicMock()

    material.name = 'Material'

    material.pbr_export_settings = mocker.MagicMock()
    material.pbr_export_settings.base_color_factor = [
        0.64000004529953,
        0.64000004529953,
        0.64000004529953,
        1.0
    ]
    material.pbr_export_settings.metallic_factor = 0.0
    material.pbr_export_settings.roughness_factor = 1.0
    material.pbr_export_settings.emissive_factor = [0.0, 0.0, 0.0]

    return material


@pytest.fixture
def gltf_material_default():
    return {
        'emissiveFactor': [
            0.0,
            0.0,
            0.0
        ],
        'name': 'Material',
        'pbrMetallicRoughness': {
            'baseColorFactor': [
                0.64000004529953,
                0.64000004529953,
                0.64000004529953,
                1.0
            ],
            'metallicFactor': 0.0,
            'roughnessFactor': 1.0
        }
    }


@pytest.fixture
def bpy_scene_default(mocker, bpy_camera_default):
    scene = mocker.MagicMock()

    scene.name = 'Scene'

    scene.world = mocker.MagicMock()
    scene.world.horizon_color = [0.05087608844041824, 0.05087608844041824, 0.05087608844041824]

    scene.render = mocker.MagicMock()
    scene.render.fps = 24

    scene.camera = bpy_camera_default
    scene.camera.data = scene.camera.name

    return scene


@pytest.fixture
def gltf_scene_default():
    return {
        "extras": {
            "active_camera": 'Camera',
            "background_color": [
                0.05087608844041824,
                0.05087608844041824,
                0.05087608844041824
            ],
            "frames_per_second": 24
        },
        "name": "Scene",
        "nodes": []
    }
