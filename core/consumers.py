# core/consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        # Reject if not authenticated
        user = self.scope.get("user", AnonymousUser())
        if not user or user.is_anonymous:
            await self.close(code=4401)  # unauthorized
            return

        self.conversation_id = self.scope["url_route"]["kwargs"]["conversation_id"]
        self.group_name = f"chat_{self.conversation_id}"

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, "group_name"):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """
        Expect JSON like: {"type": "message", "text": "hello"}
        For now we just broadcast it to the room; persistence comes later.
        """
        try:
            payload = json.loads(text_data or "{}")
        except json.JSONDecodeError:
            return

        msg_type = payload.get("type")
        text = payload.get("text", "")

        if msg_type == "message" and text:
            await self.channel_layer.group_send(
                self.group_name,
                {
                    "type": "chat.message",
                    "sender": str(self.scope["user"].id),
                    "text": text,
                },
            )

    async def chat_message(self, event):
        """Handler for group_send above."""
        await self.send(text_data=json.dumps({
            "sender": event.get("sender"),
            "text": event.get("text", ""),
        }))
