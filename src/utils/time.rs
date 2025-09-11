use std::time::SystemTime;
use chrono::{DateTime, Local};

pub fn format_datetime(time: SystemTime) -> String {
    let datetime: DateTime<Local> = time.into();
    datetime.format("%Y-%m-%d %H:%M:%S").to_string()
}
