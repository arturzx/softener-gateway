import pytest

from softener_gateway.mqtt_protocol import (
    ConnAckPacket,
    ConnectPacket,
    ConnectReturnCode,
    DisconnectPacket,
    MqttCodecError,
    MqttIncompletePacketError,
    MqttPacket,
    MqttParseError,
    PingReqPacket,
    PingRespPacket,
    PubAckPacket,
    PubCompPacket,
    PublishPacket,
    PubRecPacket,
    PubRelPacket,
    QoS,
    SubAckPacket,
    SubAckReturnCode,
    SubscribePacket,
    TopicSubscription,
    UnsubAckPacket,
    UnsubscribePacket,
    Will,
    build_packet,
    encode_remaining_length,
    parse_packet,
    parse_packets,
)


@pytest.mark.parametrize(
    "packet",
    [
        ConnectPacket(
            client_id="softener",
            clean_session=True,
            keep_alive=60,
            will=Will(
                topic="softener/status",
                payload=b"offline",
                qos=QoS.AT_LEAST_ONCE,
                retain=True,
            ),
            username="device",
            password=b"secret",
        ),
        ConnAckPacket(
            session_present=False,
            return_code=ConnectReturnCode.ACCEPTED,
        ),
        PublishPacket(
            topic="softener/data",
            payload=b'{"state":"ok"}',
            qos=QoS.AT_MOST_ONCE,
            retain=True,
        ),
        PublishPacket(
            topic="softener/data",
            payload=b"payload",
            qos=QoS.AT_LEAST_ONCE,
            packet_identifier=10,
            dup=True,
        ),
        PubAckPacket(packet_identifier=1),
        PubRecPacket(packet_identifier=2),
        PubRelPacket(packet_identifier=3),
        PubCompPacket(packet_identifier=4),
        SubscribePacket(
            packet_identifier=5,
            subscriptions=(
                TopicSubscription("softener/accepted", QoS.AT_MOST_ONCE),
                TopicSubscription("softener/rejected", QoS.AT_LEAST_ONCE),
            ),
        ),
        SubAckPacket(
            packet_identifier=5,
            return_codes=(
                SubAckReturnCode.MAXIMUM_QOS_0,
                SubAckReturnCode.FAILURE,
            ),
        ),
        UnsubscribePacket(
            packet_identifier=6,
            topic_filters=("softener/accepted", "softener/rejected"),
        ),
        UnsubAckPacket(packet_identifier=6),
        PingReqPacket(),
        PingRespPacket(),
        DisconnectPacket(),
    ],
)
def test_packet_roundtrip(packet: MqttPacket) -> None:
    encoded = build_packet(packet)

    assert parse_packet(encoded) == packet


def test_builds_known_pingreq_bytes() -> None:
    assert build_packet(PingReqPacket()) == b"\xc0\x00"


def test_builds_pubrel_with_required_fixed_header_flags() -> None:
    assert build_packet(PubRelPacket(packet_identifier=7)) == b"\x62\x02\x00\x07"


def test_parses_known_connect_packet() -> None:
    packet = parse_packet(
        b"\x10\x1b"
        b"\x00\x04MQTT"
        b"\x04"
        b"\x02"
        b"\x00\x3c"
        b"\x00\x0fsoftener-client"
    )

    assert packet == ConnectPacket(
        client_id="softener-client",
        clean_session=True,
        keep_alive=60,
    )


def test_remaining_length_uses_variable_encoding() -> None:
    payload = b"x" * 130
    encoded = build_packet(PublishPacket(topic="a/b", payload=payload))

    assert encoded[:3] == b"\x30\x87\x01"
    assert parse_packet(encoded) == PublishPacket(topic="a/b", payload=payload)


def test_parse_packets_returns_incomplete_tail() -> None:
    first = build_packet(PingReqPacket())
    second = build_packet(PingRespPacket())
    packets, remaining = parse_packets(first + second[:1])

    assert packets == (PingReqPacket(),)
    assert remaining == second[:1]


def test_parse_packet_rejects_trailing_bytes() -> None:
    with pytest.raises(MqttParseError, match="Trailing bytes"):
        parse_packet(build_packet(PingReqPacket()) + b"\x00")


def test_parse_packet_reports_incomplete_body() -> None:
    with pytest.raises(MqttIncompletePacketError):
        parse_packet(b"\x30\x04\x00")


def test_parse_packet_rejects_invalid_fixed_header_flags() -> None:
    with pytest.raises(MqttParseError, match="Invalid fixed header flags"):
        parse_packet(b"\x80\x00")


def test_parse_packet_rejects_malformed_remaining_length() -> None:
    with pytest.raises(MqttParseError, match="Malformed MQTT Remaining Length"):
        parse_packet(b"\x30\x80\x80\x80\x80")


def test_parse_subscribe_rejects_invalid_requested_qos() -> None:
    packet = b"\x82\x08\x00\x01\x00\x03a/b\x03"

    with pytest.raises(MqttParseError, match="requested QoS"):
        parse_packet(packet)


def test_build_publish_qos_zero_rejects_packet_identifier() -> None:
    packet = PublishPacket(
        topic="softener/data",
        payload=b"payload",
        packet_identifier=1,
    )

    with pytest.raises(MqttCodecError, match="QoS 0"):
        build_packet(packet)


def test_build_publish_qos_one_requires_packet_identifier() -> None:
    packet = PublishPacket(
        topic="softener/data",
        payload=b"payload",
        qos=QoS.AT_LEAST_ONCE,
    )

    with pytest.raises(MqttCodecError, match="requires a packet identifier"):
        build_packet(packet)


def test_build_connect_rejects_password_without_username() -> None:
    packet = ConnectPacket(
        client_id="softener",
        clean_session=True,
        keep_alive=60,
        password=b"secret",
    )

    with pytest.raises(MqttCodecError, match="password requires username"):
        build_packet(packet)


def test_build_connect_rejects_will_topic_with_wildcard() -> None:
    packet = ConnectPacket(
        client_id="softener",
        clean_session=True,
        keep_alive=60,
        will=Will(topic="softener/+", payload=b"offline"),
    )

    with pytest.raises(MqttCodecError, match="must not contain wildcards"):
        build_packet(packet)


def test_parse_subscribe_rejects_invalid_topic_filter_wildcard() -> None:
    topic_filter = b"softener/#/invalid"
    packet = b"\x82" + bytes([5 + len(topic_filter)]) + b"\x00\x01"
    packet += len(topic_filter).to_bytes(2, "big") + topic_filter + b"\x00"

    with pytest.raises(MqttCodecError, match="multi-level wildcard"):
        parse_packet(packet)


def test_encode_remaining_length_rejects_out_of_range_value() -> None:
    with pytest.raises(MqttCodecError, match="Remaining Length"):
        encode_remaining_length(268_435_456)
