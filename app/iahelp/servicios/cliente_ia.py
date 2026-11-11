"""
Cliente de IA compatible con la API de Groq (OpenAI-compatible).
"""

import logging
from openai import OpenAI
from django.conf import settings

logger = logging.getLogger(__name__)


class AIClient:
    """Wrapper alrededor del SDK de OpenAI apuntando al endpoint de Groq."""

    def __init__(self):
        self.client = OpenAI(
            api_key=settings.GROQ_API_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
        self.model = settings.AI_SETTINGS["MODEL"]
        self.max_retries = settings.AI_SETTINGS["MAX_RETRIES"]
        self.timeout = settings.AI_SETTINGS["TIMEOUT"]

    def chat(self, system_prompt: str, user_message: str) -> str:
        """
        Envía un mensaje al modelo y devuelve la respuesta como texto.

        Args:
            system_prompt: Instrucciones del sistema para el modelo.
            user_message: Mensaje del usuario a analizar.

        Returns:
            Texto de respuesta del modelo.

        Raises:
            Exception: Si la llamada falla después de los reintentos.
        """
        last_error = None

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.3,
                    max_tokens=1024,
                    timeout=self.timeout,
                )
                return response.choices[0].message.content

            except Exception as e:
                last_error = e
                logger.warning(
                    "Intento %d/%d falló: %s", attempt, self.max_retries, str(e)
                )
                if "unauthenticated" in str(e).lower() or "invalid_api_key" in str(e).lower():
                    logger.error("API key inválida o no autorizada; devolviendo respuesta por defecto.")
                    return "Lo siento, actualmente no puedo procesar la solicitud debido a un problema de configuración del servicio de IA."


        raise last_error
