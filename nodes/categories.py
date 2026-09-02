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


def get_base_categories():
    """Return the static Input and Output categories."""
    return [
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
            "MODLY_OUTPUTS",
            "Output",
            items=[
                NodeItem("ModlyAddToSceneNode"),
            ],
        ),
    ]

_CATEGORY_ID = "MODLY_NODES"


def register():
    try:
        nodeitems_utils.unregister_node_categories(_CATEGORY_ID)
    except KeyError:
        pass
    nodeitems_utils.register_node_categories(_CATEGORY_ID, get_base_categories())


def unregister():
    try:
        nodeitems_utils.unregister_node_categories(_CATEGORY_ID)
    except KeyError:
        pass
