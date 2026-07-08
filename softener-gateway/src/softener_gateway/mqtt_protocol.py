from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TypeAlias

MQTT_PROTOCOL_NAME = "MQTT"
MQTT_PROTOCOL_LEVEL = 4
MAX_REMAINING_LENGTH = 268_435_455
MAX_UTF8_STRING_LENGTH = 65_535
MAX_BINARY_LENGTH = 65_535


class MqttCodecError(ValueError):
    pass


class MqttParseError(MqttCodecError):
    pass


class MqttIncompletePacketError(MqttParseError):
    pass


class PacketType(IntEnum):
    CONNECT = 1
    CONNACK = 2
    PUBLISH = 3
    PUBACK = 4
    PUBREC = 5
    PUBREL = 6
    PUBCOMP = 7
    SUBSCRIBE = 8
    SUBACK = 9
    UNSUBSCRIBE = 10
    UNSUBACK = 11
    PINGREQ = 12
    PINGRESP = 13
    DISCONNECT = 14


class QoS(IntEnum):
    AT_MOST_ONCE = 0
    AT_LEAST_ONCE = 1
    EXACTLY_ONCE = 2


class ConnectReturnCode(IntEnum):
    ACCEPTED = 0
    UNACCEPTABLE_PROTOCOL_VERSION = 1
    IDENTIFIER_REJECTED = 2
    SERVER_UNAVAILABLE = 3
    BAD_USERNAME_OR_PASSWORD = 4
    NOT_AUTHORIZED = 5


class SubAckReturnCode(IntEnum):
    MAXIMUM_QOS_0 = 0
    MAXIMUM_QOS_1 = 1
    MAXIMUM_QOS_2 = 2
    FAILURE = 0x80


@dataclass(frozen=True, slots=True)
class Will:
    topic: str
    payload: bytes
    qos: QoS = QoS.AT_MOST_ONCE
    retain: bool = False


@dataclass(frozen=True, slots=True)
class TopicSubscription:
    topic_filter: str
    qos: QoS


@dataclass(frozen=True, slots=True)
class ConnectPacket:
    client_id: str
    clean_session: bool
    keep_alive: int
    will: Will | None = None
    username: str | None = None
    password: bytes | None = None


@dataclass(frozen=True, slots=True)
class ConnAckPacket:
    session_present: bool
    return_code: ConnectReturnCode


@dataclass(frozen=True, slots=True)
class PublishPacket:
    topic: str
    payload: bytes
    qos: QoS = QoS.AT_MOST_ONCE
    packet_identifier: int | None = None
    dup: bool = False
    retain: bool = False


@dataclass(frozen=True, slots=True)
class PubAckPacket:
    packet_identifier: int


@dataclass(frozen=True, slots=True)
class PubRecPacket:
    packet_identifier: int


@dataclass(frozen=True, slots=True)
class PubRelPacket:
    packet_identifier: int


@dataclass(frozen=True, slots=True)
class PubCompPacket:
    packet_identifier: int


@dataclass(frozen=True, slots=True)
class SubscribePacket:
    packet_identifier: int
    subscriptions: tuple[TopicSubscription, ...]


@dataclass(frozen=True, slots=True)
class SubAckPacket:
    packet_identifier: int
    return_codes: tuple[SubAckReturnCode, ...]


@dataclass(frozen=True, slots=True)
class UnsubscribePacket:
    packet_identifier: int
    topic_filters: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class UnsubAckPacket:
    packet_identifier: int


@dataclass(frozen=True, slots=True)
class PingReqPacket:
    pass


@dataclass(frozen=True, slots=True)
class PingRespPacket:
    pass


@dataclass(frozen=True, slots=True)
class DisconnectPacket:
    pass


MqttPacket: TypeAlias = (
    ConnectPacket
    | ConnAckPacket
    | PublishPacket
    | PubAckPacket
    | PubRecPacket
    | PubRelPacket
    | PubCompPacket
    | SubscribePacket
    | SubAckPacket
    | UnsubscribePacket
    | UnsubAckPacket
    | PingReqPacket
    | PingRespPacket
    | DisconnectPacket
)


_RESERVED_FLAGS: dict[PacketType, int] = {
    PacketType.CONNECT: 0x0,
    PacketType.CONNACK: 0x0,
    PacketType.PUBACK: 0x0,
    PacketType.PUBREC: 0x0,
    PacketType.PUBREL: 0x2,
    PacketType.PUBCOMP: 0x0,
    PacketType.SUBSCRIBE: 0x2,
    PacketType.SUBACK: 0x0,
    PacketType.UNSUBSCRIBE: 0x2,
    PacketType.UNSUBACK: 0x0,
    PacketType.PINGREQ: 0x0,
    PacketType.PINGRESP: 0x0,
    PacketType.DISCONNECT: 0x0,
}


class _Reader:
    def __init__(self, data: bytes) -> None:
        self._data = data
        self.offset = 0

    @property
    def remaining(self) -> int:
        return len(self._data) - self.offset

    @property
    def at_end(self) -> bool:
        return self.offset == len(self._data)

    def read_byte(self) -> int:
        return self.read(1)[0]

    def read_uint16(self) -> int:
        data = self.read(2)
        return int.from_bytes(data, "big")

    def read(self, length: int) -> bytes:
        end = self.offset + length
        if end > len(self._data):
            raise MqttIncompletePacketError("Incomplete MQTT packet")

        data = self._data[self.offset : end]
        self.offset = end
        return data

    def read_remaining(self) -> bytes:
        return self.read(self.remaining)


def parse_packet(data: bytes) -> MqttPacket:
    packet, packet_length = _parse_one(data)
    if packet_length != len(data):
        raise MqttParseError("Trailing bytes after MQTT packet")

    return packet


def parse_packets(data: bytes) -> tuple[tuple[MqttPacket, ...], bytes]:
    packets: list[MqttPacket] = []
    offset = 0

    while offset < len(data):
        try:
            packet, packet_length = _parse_one(data[offset:])
        except MqttIncompletePacketError:
            break

        packets.append(packet)
        offset += packet_length

    return tuple(packets), data[offset:]


def build_packet(packet: MqttPacket) -> bytes:
    packet_type, flags, body = _build_packet_body(packet)
    return bytes([(packet_type.value << 4) | flags]) + encode_remaining_length(len(body)) + body


def encode_remaining_length(value: int) -> bytes:
    if value < 0 or value > MAX_REMAINING_LENGTH:
        raise MqttCodecError("MQTT Remaining Length must be between 0 and 268435455")

    encoded = bytearray()
    while True:
        encoded_byte = value % 128
        value //= 128
        if value > 0:
            encoded_byte |= 0x80

        encoded.append(encoded_byte)
        if value == 0:
            return bytes(encoded)


def _parse_one(data: bytes) -> tuple[MqttPacket, int]:
    if not data:
        raise MqttIncompletePacketError("Incomplete MQTT fixed header")

    first_byte = data[0]
    packet_type_value = first_byte >> 4
    flags = first_byte & 0x0F

    try:
        packet_type = PacketType(packet_type_value)
    except ValueError as exc:
        raise MqttParseError(f"Invalid MQTT packet type: {packet_type_value}") from exc

    remaining_length, remaining_length_size = _decode_remaining_length(data, 1)
    fixed_header_length = 1 + remaining_length_size
    total_length = fixed_header_length + remaining_length

    if len(data) < total_length:
        raise MqttIncompletePacketError("Incomplete MQTT packet body")

    body = data[fixed_header_length:total_length]
    packet = _parse_packet_body(packet_type, flags, body)
    return packet, total_length


def _decode_remaining_length(data: bytes, offset: int) -> tuple[int, int]:
    multiplier = 1
    value = 0

    for size in range(1, 5):
        if offset >= len(data):
            raise MqttIncompletePacketError("Incomplete MQTT Remaining Length")

        encoded_byte = data[offset]
        offset += 1
        value += (encoded_byte & 0x7F) * multiplier

        if encoded_byte & 0x80 == 0:
            return value, size

        multiplier *= 128

    raise MqttParseError("Malformed MQTT Remaining Length")


def _parse_packet_body(packet_type: PacketType, flags: int, body: bytes) -> MqttPacket:
    if packet_type is PacketType.PUBLISH:
        return _parse_publish(flags, body)

    expected_flags = _RESERVED_FLAGS[packet_type]
    if flags != expected_flags:
        raise MqttParseError(
            f"Invalid fixed header flags for {packet_type.name}: 0x{flags:x}"
        )

    match packet_type:
        case PacketType.CONNECT:
            return _parse_connect(body)
        case PacketType.CONNACK:
            return _parse_connack(body)
        case PacketType.PUBACK:
            return PubAckPacket(_parse_packet_identifier_body(body))
        case PacketType.PUBREC:
            return PubRecPacket(_parse_packet_identifier_body(body))
        case PacketType.PUBREL:
            return PubRelPacket(_parse_packet_identifier_body(body))
        case PacketType.PUBCOMP:
            return PubCompPacket(_parse_packet_identifier_body(body))
        case PacketType.SUBSCRIBE:
            return _parse_subscribe(body)
        case PacketType.SUBACK:
            return _parse_suback(body)
        case PacketType.UNSUBSCRIBE:
            return _parse_unsubscribe(body)
        case PacketType.UNSUBACK:
            return UnsubAckPacket(_parse_packet_identifier_body(body))
        case PacketType.PINGREQ:
            _require_empty_body(packet_type, body)
            return PingReqPacket()
        case PacketType.PINGRESP:
            _require_empty_body(packet_type, body)
            return PingRespPacket()
        case PacketType.DISCONNECT:
            _require_empty_body(packet_type, body)
            return DisconnectPacket()


def _parse_connect(body: bytes) -> ConnectPacket:
    reader = _Reader(body)
    protocol_name = _read_utf8_string(reader)
    protocol_level = reader.read_byte()
    connect_flags = reader.read_byte()
    keep_alive = reader.read_uint16()

    if protocol_name != MQTT_PROTOCOL_NAME:
        raise MqttParseError(f"Unsupported MQTT protocol name: {protocol_name!r}")
    if protocol_level != MQTT_PROTOCOL_LEVEL:
        raise MqttParseError(f"Unsupported MQTT protocol level: {protocol_level}")
    if connect_flags & 0x01:
        raise MqttParseError("CONNECT reserved flag bit must be 0")

    username_flag = bool(connect_flags & 0x80)
    password_flag = bool(connect_flags & 0x40)
    will_retain = bool(connect_flags & 0x20)
    will_qos_value = (connect_flags >> 3) & 0x03
    will_flag = bool(connect_flags & 0x04)
    clean_session = bool(connect_flags & 0x02)

    if password_flag and not username_flag:
        raise MqttParseError("CONNECT password flag requires username flag")
    if not will_flag and (will_qos_value != 0 or will_retain):
        raise MqttParseError("CONNECT will QoS and retain must be 0 when will flag is not set")
    if will_qos_value == 3:
        raise MqttParseError("CONNECT will QoS must be 0, 1, or 2")

    client_id = _read_utf8_string(reader)
    will = None
    if will_flag:
        will = Will(
            topic=_read_utf8_string(reader),
            payload=_read_binary(reader),
            qos=QoS(will_qos_value),
            retain=will_retain,
        )

    username = _read_utf8_string(reader) if username_flag else None
    password = _read_binary(reader) if password_flag else None
    _require_reader_consumed(reader)

    return ConnectPacket(
        client_id=client_id,
        clean_session=clean_session,
        keep_alive=keep_alive,
        will=will,
        username=username,
        password=password,
    )


def _parse_connack(body: bytes) -> ConnAckPacket:
    if len(body) != 2:
        raise MqttParseError("CONNACK body must be exactly 2 bytes")

    acknowledge_flags = body[0]
    return_code_value = body[1]
    if acknowledge_flags & 0xFE:
        raise MqttParseError("CONNACK reserved acknowledge flag bits must be 0")

    try:
        return_code = ConnectReturnCode(return_code_value)
    except ValueError as exc:
        raise MqttParseError(f"Invalid CONNACK return code: {return_code_value}") from exc

    session_present = bool(acknowledge_flags & 0x01)
    if return_code is not ConnectReturnCode.ACCEPTED and session_present:
        raise MqttParseError("CONNACK session present must be false for non-zero return code")

    return ConnAckPacket(session_present=session_present, return_code=return_code)


def _parse_publish(flags: int, body: bytes) -> PublishPacket:
    dup = bool(flags & 0x08)
    qos_value = (flags >> 1) & 0x03
    retain = bool(flags & 0x01)

    if qos_value == 3:
        raise MqttParseError("PUBLISH QoS must be 0, 1, or 2")
    if qos_value == QoS.AT_MOST_ONCE and dup:
        raise MqttParseError("PUBLISH DUP must be 0 for QoS 0")

    qos = QoS(qos_value)
    reader = _Reader(body)
    topic = _read_utf8_string(reader)
    _validate_publish_topic(topic)
    packet_identifier = None
    if qos is not QoS.AT_MOST_ONCE:
        packet_identifier = _read_packet_identifier(reader)

    return PublishPacket(
        topic=topic,
        payload=reader.read_remaining(),
        qos=qos,
        packet_identifier=packet_identifier,
        dup=dup,
        retain=retain,
    )


def _parse_subscribe(body: bytes) -> SubscribePacket:
    reader = _Reader(body)
    packet_identifier = _read_packet_identifier(reader)
    subscriptions: list[TopicSubscription] = []

    while not reader.at_end:
        topic_filter = _read_utf8_string(reader)
        _validate_topic_filter(topic_filter)
        requested_qos = reader.read_byte()
        if requested_qos & 0xFC:
            raise MqttParseError("SUBSCRIBE requested QoS reserved bits must be 0")
        if requested_qos > QoS.EXACTLY_ONCE:
            raise MqttParseError("SUBSCRIBE requested QoS must be 0, 1, or 2")

        subscriptions.append(
            TopicSubscription(topic_filter=topic_filter, qos=QoS(requested_qos))
        )

    if not subscriptions:
        raise MqttParseError("SUBSCRIBE payload must contain at least one topic filter")

    return SubscribePacket(
        packet_identifier=packet_identifier,
        subscriptions=tuple(subscriptions),
    )


def _parse_suback(body: bytes) -> SubAckPacket:
    reader = _Reader(body)
    packet_identifier = _read_packet_identifier(reader)
    return_codes: list[SubAckReturnCode] = []

    while not reader.at_end:
        value = reader.read_byte()
        try:
            return_codes.append(SubAckReturnCode(value))
        except ValueError as exc:
            raise MqttParseError(f"Invalid SUBACK return code: {value}") from exc

    if not return_codes:
        raise MqttParseError("SUBACK payload must contain at least one return code")

    return SubAckPacket(
        packet_identifier=packet_identifier,
        return_codes=tuple(return_codes),
    )


def _parse_unsubscribe(body: bytes) -> UnsubscribePacket:
    reader = _Reader(body)
    packet_identifier = _read_packet_identifier(reader)
    topic_filters: list[str] = []

    while not reader.at_end:
        topic_filter = _read_utf8_string(reader)
        _validate_topic_filter(topic_filter)
        topic_filters.append(topic_filter)

    if not topic_filters:
        raise MqttParseError("UNSUBSCRIBE payload must contain at least one topic filter")

    return UnsubscribePacket(
        packet_identifier=packet_identifier,
        topic_filters=tuple(topic_filters),
    )


def _parse_packet_identifier_body(body: bytes) -> int:
    if len(body) != 2:
        raise MqttParseError("Packet identifier body must be exactly 2 bytes")

    return _validate_packet_identifier(int.from_bytes(body, "big"))


def _build_packet_body(packet: MqttPacket) -> tuple[PacketType, int, bytes]:
    match packet:
        case ConnectPacket():
            return PacketType.CONNECT, 0x0, _build_connect(packet)
        case ConnAckPacket():
            return PacketType.CONNACK, 0x0, _build_connack(packet)
        case PublishPacket():
            return PacketType.PUBLISH, _publish_flags(packet), _build_publish(packet)
        case PubAckPacket():
            return PacketType.PUBACK, 0x0, _build_packet_identifier(packet.packet_identifier)
        case PubRecPacket():
            return PacketType.PUBREC, 0x0, _build_packet_identifier(packet.packet_identifier)
        case PubRelPacket():
            return PacketType.PUBREL, 0x2, _build_packet_identifier(packet.packet_identifier)
        case PubCompPacket():
            return PacketType.PUBCOMP, 0x0, _build_packet_identifier(packet.packet_identifier)
        case SubscribePacket():
            return PacketType.SUBSCRIBE, 0x2, _build_subscribe(packet)
        case SubAckPacket():
            return PacketType.SUBACK, 0x0, _build_suback(packet)
        case UnsubscribePacket():
            return PacketType.UNSUBSCRIBE, 0x2, _build_unsubscribe(packet)
        case UnsubAckPacket():
            return PacketType.UNSUBACK, 0x0, _build_packet_identifier(packet.packet_identifier)
        case PingReqPacket():
            return PacketType.PINGREQ, 0x0, b""
        case PingRespPacket():
            return PacketType.PINGRESP, 0x0, b""
        case DisconnectPacket():
            return PacketType.DISCONNECT, 0x0, b""


def _build_connect(packet: ConnectPacket) -> bytes:
    _validate_uint16(packet.keep_alive, "CONNECT keep alive")
    if packet.password is not None and packet.username is None:
        raise MqttCodecError("CONNECT password requires username")

    connect_flags = 0
    payload = bytearray()
    payload.extend(_encode_utf8_string(packet.client_id))

    if packet.clean_session:
        connect_flags |= 0x02

    if packet.will is not None:
        _validate_publish_topic(packet.will.topic)
        if packet.will.qos not in QoS:
            raise MqttCodecError("CONNECT will QoS must be 0, 1, or 2")

        connect_flags |= 0x04
        connect_flags |= packet.will.qos.value << 3
        if packet.will.retain:
            connect_flags |= 0x20
        payload.extend(_encode_utf8_string(packet.will.topic))
        payload.extend(_encode_binary(packet.will.payload))

    if packet.username is not None:
        connect_flags |= 0x80
        payload.extend(_encode_utf8_string(packet.username))

    if packet.password is not None:
        connect_flags |= 0x40
        payload.extend(_encode_binary(packet.password))

    return (
        _encode_utf8_string(MQTT_PROTOCOL_NAME)
        + bytes([MQTT_PROTOCOL_LEVEL, connect_flags])
        + _encode_uint16(packet.keep_alive)
        + bytes(payload)
    )


def _build_connack(packet: ConnAckPacket) -> bytes:
    if packet.return_code is not ConnectReturnCode.ACCEPTED and packet.session_present:
        raise MqttCodecError("CONNACK session present must be false for non-zero return code")

    acknowledge_flags = 0x01 if packet.session_present else 0x00
    return bytes([acknowledge_flags, packet.return_code.value])


def _publish_flags(packet: PublishPacket) -> int:
    if packet.qos is QoS.AT_MOST_ONCE:
        if packet.packet_identifier is not None:
            raise MqttCodecError("PUBLISH QoS 0 must not contain a packet identifier")
        if packet.dup:
            raise MqttCodecError("PUBLISH DUP must be false for QoS 0")
    else:
        if packet.packet_identifier is None:
            raise MqttCodecError("PUBLISH QoS 1/2 requires a packet identifier")

    flags = packet.qos.value << 1
    if packet.dup:
        flags |= 0x08
    if packet.retain:
        flags |= 0x01

    return flags


def _build_publish(packet: PublishPacket) -> bytes:
    _validate_publish_topic(packet.topic)
    body = bytearray()
    body.extend(_encode_utf8_string(packet.topic))
    if packet.qos is not QoS.AT_MOST_ONCE:
        assert packet.packet_identifier is not None
        body.extend(_build_packet_identifier(packet.packet_identifier))
    body.extend(packet.payload)
    return bytes(body)


def _build_subscribe(packet: SubscribePacket) -> bytes:
    if not packet.subscriptions:
        raise MqttCodecError("SUBSCRIBE must contain at least one topic filter")

    body = bytearray(_build_packet_identifier(packet.packet_identifier))
    for subscription in packet.subscriptions:
        _validate_topic_filter(subscription.topic_filter)
        if subscription.qos not in QoS:
            raise MqttCodecError("SUBSCRIBE QoS must be 0, 1, or 2")

        body.extend(_encode_utf8_string(subscription.topic_filter))
        body.append(subscription.qos.value)

    return bytes(body)


def _build_suback(packet: SubAckPacket) -> bytes:
    if not packet.return_codes:
        raise MqttCodecError("SUBACK must contain at least one return code")

    return _build_packet_identifier(packet.packet_identifier) + bytes(
        return_code.value for return_code in packet.return_codes
    )


def _build_unsubscribe(packet: UnsubscribePacket) -> bytes:
    if not packet.topic_filters:
        raise MqttCodecError("UNSUBSCRIBE must contain at least one topic filter")

    body = bytearray(_build_packet_identifier(packet.packet_identifier))
    for topic_filter in packet.topic_filters:
        _validate_topic_filter(topic_filter)
        body.extend(_encode_utf8_string(topic_filter))

    return bytes(body)


def _read_utf8_string(reader: _Reader) -> str:
    data = _read_binary(reader)
    try:
        value = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MqttParseError("Invalid MQTT UTF-8 string") from exc

    _validate_mqtt_utf8(value)
    return value


def _read_binary(reader: _Reader) -> bytes:
    length = reader.read_uint16()
    return reader.read(length)


def _read_packet_identifier(reader: _Reader) -> int:
    return _validate_packet_identifier(reader.read_uint16())


def _encode_utf8_string(value: str) -> bytes:
    _validate_mqtt_utf8(value)
    data = value.encode("utf-8")
    if len(data) > MAX_UTF8_STRING_LENGTH:
        raise MqttCodecError("MQTT UTF-8 string exceeds 65535 bytes")

    return _encode_uint16(len(data)) + data


def _encode_binary(value: bytes) -> bytes:
    if len(value) > MAX_BINARY_LENGTH:
        raise MqttCodecError("MQTT binary field exceeds 65535 bytes")

    return _encode_uint16(len(value)) + value


def _encode_uint16(value: int) -> bytes:
    _validate_uint16(value, "MQTT 16-bit integer")
    return value.to_bytes(2, "big")


def _build_packet_identifier(packet_identifier: int) -> bytes:
    return _encode_uint16(_validate_packet_identifier(packet_identifier))


def _validate_uint16(value: int, field_name: str) -> None:
    if value < 0 or value > 0xFFFF:
        raise MqttCodecError(f"{field_name} must be between 0 and 65535")


def _validate_packet_identifier(packet_identifier: int) -> int:
    if packet_identifier < 1 or packet_identifier > 0xFFFF:
        raise MqttCodecError("MQTT packet identifier must be between 1 and 65535")

    return packet_identifier


def _validate_mqtt_utf8(value: str) -> None:
    for character in value:
        codepoint = ord(character)
        if codepoint == 0:
            raise MqttCodecError("MQTT UTF-8 string must not contain U+0000")
        if 0xD800 <= codepoint <= 0xDFFF:
            raise MqttCodecError("MQTT UTF-8 string must not contain surrogate code points")


def _validate_publish_topic(topic: str) -> None:
    if not topic:
        raise MqttCodecError("MQTT publish topic must not be empty")
    if "+" in topic or "#" in topic:
        raise MqttCodecError("MQTT publish topic must not contain wildcards")

    _validate_mqtt_utf8(topic)


def _validate_topic_filter(topic_filter: str) -> None:
    if not topic_filter:
        raise MqttCodecError("MQTT topic filter must not be empty")

    _validate_mqtt_utf8(topic_filter)
    for index, character in enumerate(topic_filter):
        if character == "#":
            if index != len(topic_filter) - 1:
                raise MqttCodecError("MQTT multi-level wildcard must be the last character")
            if index > 0 and topic_filter[index - 1] != "/":
                raise MqttCodecError("MQTT multi-level wildcard must occupy an entire level")
        elif character == "+":
            if index > 0 and topic_filter[index - 1] != "/":
                raise MqttCodecError("MQTT single-level wildcard must occupy an entire level")
            if index < len(topic_filter) - 1 and topic_filter[index + 1] != "/":
                raise MqttCodecError("MQTT single-level wildcard must occupy an entire level")


def _require_empty_body(packet_type: PacketType, body: bytes) -> None:
    if body:
        raise MqttParseError(f"{packet_type.name} body must be empty")


def _require_reader_consumed(reader: _Reader) -> None:
    if not reader.at_end:
        raise MqttParseError("Unexpected trailing bytes in MQTT packet body")


__all__ = [
    "ConnectPacket",
    "ConnectReturnCode",
    "ConnAckPacket",
    "DisconnectPacket",
    "MAX_REMAINING_LENGTH",
    "MQTT_PROTOCOL_LEVEL",
    "MQTT_PROTOCOL_NAME",
    "MqttCodecError",
    "MqttIncompletePacketError",
    "MqttPacket",
    "MqttParseError",
    "PacketType",
    "PingReqPacket",
    "PingRespPacket",
    "PubAckPacket",
    "PubCompPacket",
    "PubRecPacket",
    "PubRelPacket",
    "PublishPacket",
    "QoS",
    "SubAckPacket",
    "SubAckReturnCode",
    "SubscribePacket",
    "TopicSubscription",
    "UnsubAckPacket",
    "UnsubscribePacket",
    "Will",
    "build_packet",
    "encode_remaining_length",
    "parse_packet",
    "parse_packets",
]
