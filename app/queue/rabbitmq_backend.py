"""RabbitMQ-backed queue implementation using aio-pika.

Uses a single durable-false queue to mirror Redis LIST semantics.
pop() uses basic_get with a 1s retry loop to emulate BRPOP behaviour.
"""
from __future__ import annotations

import asyncio
import logging
import time

import aio_pika
from aio_pika.abc import AbstractRobustConnection, AbstractChannel, AbstractQueue

logger = logging.getLogger(__name__)


class RabbitMQQueueBackend:
    def __init__(
        self,
        connection: AbstractRobustConnection,
        channel: AbstractChannel,
        queue: AbstractQueue,
        queue_name: str,
    ) -> None:
        self._connection = connection
        self._channel = channel
        self._queue = queue
        self._queue_name = queue_name

    @classmethod
    async def create(cls, url: str, queue_name: str) -> "RabbitMQQueueBackend":
        """Connect to RabbitMQ and declare the inference queue."""
        connection = await aio_pika.connect_robust(url)
        channel = await connection.channel()
        await channel.set_qos(prefetch_count=1)
        queue = await channel.declare_queue(queue_name, durable=False)
        logger.info("RabbitMQ queue '%s' ready", queue_name)
        return cls(connection, channel, queue, queue_name)

    async def push(self, data: str) -> float:
        """Publish message to the default exchange. Returns push duration in ms."""
        t0 = time.monotonic()
        await self._channel.default_exchange.publish(
            aio_pika.Message(body=data.encode()),
            routing_key=self._queue_name,
        )
        return (time.monotonic() - t0) * 1000

    async def pop(self) -> str | None:
        """basic_get with up to 1s polling to emulate BRPOP.

        Returns message body as str, or None if no message within 1s.
        """
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline:
            try:
                message = await self._queue.get(no_ack=True)
                return message.body.decode()
            except aio_pika.exceptions.QueueEmpty:
                await asyncio.sleep(0.05)
        return None

    async def length(self) -> int:
        """Return current message count via passive queue declaration."""
        q = await self._channel.declare_queue(self._queue_name, passive=True)
        return q.declaration_result.message_count

    async def close(self) -> None:
        """Close RabbitMQ connection."""
        await self._connection.close()
        logger.info("RabbitMQ connection closed")
