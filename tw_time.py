import datetime
try:
    import zoneinfo
except ImportError:
    zoneinfo = None
try:
    import pytz
except ImportError:
    pytz = None

def get_current_date_time(tz_string="Europe/Bucharest"):
    # get current datetime formatted as string with timezone
    _time_zone   = None
    _now         = None
    _result_str  = ""
    try:
        if zoneinfo is not None:
            _time_zone   = zoneinfo.ZoneInfo(tz_string)
            _now         = datetime.datetime.now(_time_zone)
        else:
            if pytz is not None:
                _time_zone   = pytz.timezone(tz_string)
                _now         = datetime.datetime.now(_time_zone)
            else:
                # fallback if timezone information is not available
                _now         = datetime.datetime.now()
    except Exception:
        # fallback if timezone information is not available
        _now         = datetime.datetime.now()
    if _now is not None:
        _result_str  = _now.strftime("%Y-%m-%d %H:%M:%S")
    else:
        # should not happen but handle fallback
        _result_str  = "unknown"
    return _result_str


def get_date_time_from_timestamp(timestamp_seconds, tz_string="Europe/Bucharest"):
    # convert unix timestamp in seconds to formatted datetime string with timezone
    _time_zone   = None
    _dt_obj      = None
    _result_str  = ""
    try:
        _int_ts      = int(timestamp_seconds)
        if zoneinfo is not None:
            _time_zone   = zoneinfo.ZoneInfo(tz_string)
            _dt_obj      = datetime.datetime.fromtimestamp(
                _int_ts,
                _time_zone)
        else:
            if pytz is not None:
                _time_zone   = pytz.timezone(tz_string)
                _dt_obj      = datetime.datetime.fromtimestamp(
                    _int_ts,
                    _time_zone)
            else:
                # fallback if timezone information is not available
                _dt_obj      = datetime.datetime.fromtimestamp(_int_ts)
    except Exception:
        # fallback if timestamp parsing or timezone conversion fails
        _dt_obj      = None
    if _dt_obj is not None:
        _result_str  = _dt_obj.strftime("%Y-%m-%d %H:%M:%S")
    else:
        # fallback if timestamp conversion failed
        _result_str  = "unknown"
    return _result_str


