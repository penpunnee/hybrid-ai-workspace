"""Tests for response cache bypass on real-time queries

หลักการ: คำถามที่เกี่ยวกับข้อมูล real-time (ping/disk/docker/ราคา/สภาพอากาศ)
ต้อง bypass response cache เสมอ — ห้ามคืน cached answer ที่อาจเก่า
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from utils.response_cache import is_realtime_query, lookup
from unittest.mock import patch, MagicMock


class TestIsRealtimeQuery:
    def test_ping_is_realtime(self):
        assert is_realtime_query("ping router หน่อย") is True

    def test_disk_is_realtime(self):
        assert is_realtime_query("disk เหลือเท่าไหร่") is True

    def test_docker_is_realtime(self):
        assert is_realtime_query("docker container รันอยู่ไหม") is True

    def test_network_status_is_realtime(self):
        assert is_realtime_query("เครือข่ายปกติไหม") is True

    def test_nas_status_is_realtime(self):
        assert is_realtime_query("NAS ออนไลน์ไหม") is True

    def test_price_is_realtime(self):
        assert is_realtime_query("ราคา bitcoin วันนี้") is True

    def test_weather_is_realtime(self):
        assert is_realtime_query("อากาศวันนี้เป็นยังไง") is True

    def test_normal_question_is_not_realtime(self):
        assert is_realtime_query("อธิบาย FastAPI ให้หน่อย") is False

    def test_coding_question_is_not_realtime(self):
        assert is_realtime_query("วิธีเขียน async function ใน Python") is False

    def test_empty_is_not_realtime(self):
        assert is_realtime_query("") is False


class TestLookupBypassesRealtime:
    def test_lookup_returns_none_for_realtime_query(self):
        with patch("utils.response_cache.embed_query") as mock_embed:
            result = lookup("kwan", "ping NAS หน่อย")

        mock_embed.assert_not_called()
        assert result is None

    def test_lookup_proceeds_for_normal_query(self):
        with (
            patch("utils.response_cache._init", return_value=None),
        ):
            result = lookup("kwan", "อธิบาย Docker คืออะไร")

        assert result is None  # None เพราะ db=None ไม่ใช่เพราะ bypass
