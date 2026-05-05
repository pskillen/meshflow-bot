"""Meshtastic-specific implementation of the protocol-agnostic radio core.

Everything that imports from the ``meshtastic`` Python package, references
``MeshPacket``, or talks Meshtastic pubsub belongs here. The bot only ever
talks to :class:`src.meshtastic.radio.MeshtasticRadio` via the
:class:`~src.radio.interface.RadioInterface` ABC.
"""
