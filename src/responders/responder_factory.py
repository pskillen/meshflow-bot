import importlib
import re


class ResponderFactory:
    responders = [
        {
            "class": "src.responders.message_reaction_responder.MessageReactionResponder",
            "trigger_regex": [
                re.compile(r"^test$", re.IGNORECASE),
                re.compile(r"^test .*$", re.IGNORECASE),
                re.compile(r"^testing$", re.IGNORECASE),
                re.compile(r"^testing .*$", re.IGNORECASE),
            ],
            "args": ["👍🔉👂✅📡👋🐭"],
        },
    ]

    @staticmethod
    def match_responder(message: str, bot):
        for responder_info in ResponderFactory.responders:
            for pattern in responder_info["trigger_regex"]:
                if pattern.match(message):
                    return ResponderFactory.create_responder(responder_info, bot)
        return None

    @staticmethod
    def create_responder(responder_info, bot):
        module_name, class_name = responder_info["class"].rsplit(".", 1)
        module = importlib.import_module(module_name)
        responder_class = getattr(module, class_name)
        args = [bot] + responder_info["args"]
        return responder_class(*args)
