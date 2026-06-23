import datetime

def calculate_next_publish_time(current_utc: datetime.datetime, channel_profile: str) -> datetime.datetime:
    """
    Calculate the next optimal publishing window.
    US/EN profiles: Peak is 15:00 - 18:00 EST/EDT. Target 15:00.
    JST/JP profiles: Peak is 18:00 - 22:00 JST. Target 18:00.
    Enforces a minimum of 15-minute future buffer.
    """
    profile_lower = channel_profile.lower()
    
    # Check if the channel targets North America (EST/EDT)
    is_na = any(term in profile_lower for term in ["en", "aquatic_en", "beauty_en", "aesthetic"])
    
    if is_na:
        # Determine DST for Eastern Time (starts 2nd Sunday of March, ends 1st Sunday of November)
        year = current_utc.year
        
        # 2nd Sunday in March
        dst_start = datetime.datetime(year, 3, 8, 2, 0)
        while dst_start.weekday() != 6:
            dst_start += datetime.timedelta(days=1)
            
        # 1st Sunday in November
        dst_end = datetime.datetime(year, 11, 1, 2, 0)
        while dst_end.weekday() != 6:
            dst_end += datetime.timedelta(days=1)
            
        if dst_start <= current_utc < dst_end:
            # EDT (UTC-4)
            offset_hours = -4
        else:
            # EST (UTC-5)
            offset_hours = -5
            
        target_hour = 15
        target_minute = 0
    else:
        # JST (UTC+9)
        offset_hours = 9
        target_hour = 18
        target_minute = 0
        
    # Convert current UTC time to local target time
    local_now = current_utc + datetime.timedelta(hours=offset_hours)
    
    # Candidate time for today
    candidate = local_now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    
    # Enforce minimum 15-minute future buffer
    min_buffer = datetime.timedelta(minutes=15)
    if candidate < local_now + min_buffer:
        # If candidate has passed or is too close, shift to tomorrow
        candidate += datetime.timedelta(days=1)
        
    # Convert candidate local time back to UTC
    scheduled_utc = candidate - datetime.timedelta(hours=offset_hours)
    return scheduled_utc
