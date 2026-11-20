"""Журнал бота не должен содержать ответы анкеты."""

from bot.main import describe_message


def test_describe_message_hides_answers():
    assert describe_message("/start") == "cmd=/start"
    assert describe_message("/forecast extra 15.01.1990") == "cmd=/forecast"
    assert describe_message("15.01.1990") == "text len=10"
    assert "Москва" not in describe_message("Москва")
    assert describe_message(None) == "non-text"
