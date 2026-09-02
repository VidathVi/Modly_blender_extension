"""
Node categories for the Modly node editor's Add menu.
"""
from __future__ import annotations

import bpy
import nodeitems_utils
from nodeitems_utils import NodeCategory, NodeItem


class ModlyNodeCategory(NodeCategory):
    """Category of nodes shown in the Modly editor Add menu."""

    @classmethod
    def poll(cls, context):
        return context.space_data.tree_type == "ModlyNodeTree"


# Categories and their items
_node_categories = [
    ModlyNodeCategory(
        "MODLY_INPUTS",
        "Input",
        items=[
            NodeItem("ModlyImageInputNode"),
            NodeItem("ModlyTextPromptNode"),
            NodeItem("ModlySelectionInNode"),
        ],
    ),
    ModlyNodeCategory(
        "MODLY_GENERATORS",
        "Generators",
        items=[
            NodeItem("ModlyGenerateMeshNode"),
            NodeItem("ModlyTextureMeshNode"),
        ],
    ),
    ModlyNodeCategory(
        "MODLY_TRELLIS_TEXT",
        "Trellis Text",
        items=[
            NodeItem("ModlyTrellisTextBaseNode"),
            NodeItem("ModlyTrellisTextLargeNode"),
            NodeItem("ModlyTrellisTextXLNode"),
        ],
    ),
    ModlyNodeCategory(
        "MODLY_OUTPUTS",
        "Output",
        items=[
            NodeItem("ModlyAddToSceneNode"),
        ],
    ),
]

_CATEGORY_ID = "MODLY_NODES"


def register():
    nodeitems_utils.register_node_categories(_CATEGORY_ID, _node_categories)


def unregister():
    nodeitems_utils.unregister_node_categories(_CATEGORY_ID)
