use anyhow::{Result, bail};
use reqwest::Client;
use serde_json::Value;

const DOUYIN_UA: &str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 \
(KHTML, like Gecko) Chrome/92.0.4515.159 Safari/537.36";

const DOUYIN_COOKIE: &str = "enter_pc_once=1; UIFID_TEMP=29a1f63ec682dc0a0df227dd163e2b46e3a6390e403335fa4c2c6d1dc0ec5ffa7a288170e8828ecb8b2f0f16b3219daa18ad5d7faf7fb5fbb64df454c3b471cc1db9c0b5eb2cbc8e0cb1e690f5c1fbd6; \
stream_recommend_feed_params=%22%7B%5C%22cookie_enabled%5C%22%3Atrue%2C%5C%22screen_width%5C%22%3A2560%2C%5C%22screen_height%5C%22%3A1440%2C%5C%22browser_online%5C%22%3Atrue%2C%5C%22cpu_core_num%5C%22%3A16%2C%5C%22device_memory%5C%22%3A8%2C%5C%22downlink%5C%22%3A10%2C%5C%22effective_type%5C%22%3A%5C%224g%5C%22%2C%5C%22round_trip_time%5C%22%3A50%7D%22; \
hevc_supported=true; odin_tt=363047b47492a2e153d67e7022684ffd83726a0c57322991e6650da1dbe2fc0adb471e8be38efa85bf0ab9788a8e237d481c8fc488ef859f4476fc6ffd50dd31a258add2954b3fcf03cd546357df6a53; \
strategyABtestKey=%221772897157.15%22; passport_csrf_token=d71952d93315e4df5cc8373e4cdc2447; passport_csrf_token_default=d71952d93315e4df5cc8373e4cdc2447; \
home_can_add_dy_2_desktop=%221%22; biz_trace_id=fab9d888; \
ttwid=1%7CP0feYUzzIsbXr2aaLLBWHYtwVD4-6CV2voO9bAUQ7PU%7C1772897161%7Cd72bed8f6f576a1dfb7b8d1032c76706ce93b3ba3ac5b21e79501db1c2f17c9f; \
__security_mc_1_s_sdk_crypt_sdk=0ef27763-40a0-b3c3; \
is_dash_user=1; x-web-secsdk-uid=17063330-58d4-4719-9971-dba52fc661ab; \
__live_version__=%221.1.4.9549%22; has_avx2=null; device_web_cpu_core=16; device_web_memory_size=8; \
webcast_local_quality=null; live_use_vvc=%22false%22; csrf_session_id=5fe8f9d1180e55817920dae0808993ba; \
h265ErrorNum=-1; IsDouyinActive=false; live_can_add_dy_2_desktop=%220%22";

pub async fn get_flv_url(room_id: &str) -> Result<String> {
    let client = Client::new();
    let params = format!(
        "aid=6383&app_name=douyin_web&live_id=1&device_platform=web&\
         browser_language=zh-CN&browser_platform=Win32&browser_name=Edge&\
         browser_version=139.0.0.0&is_need_double_stream=false&web_rid={room_id}"
    );
    let url = format!("https://live.douyin.com/webcast/room/web/enter/?{params}");
    let resp: Value = client
        .get(&url)
        .header("User-Agent", DOUYIN_UA)
        .header("referer", "https://live.douyin.com/")
        .header("cookie", DOUYIN_COOKIE)
        .send()
        .await?
        .json()
        .await?;

    if resp.get("status_code").and_then(Value::as_i64) != Some(0) {
        bail!("抖音接口返回错误: status_code != 0");
    }
    let data = resp
        .pointer("/data/data/0")
        .ok_or_else(|| anyhow::anyhow!("缺少直播间数据"))?;
    let status = data.get("status").and_then(Value::as_i64).unwrap_or(-1);
    match status {
        2 => {}
        4 => bail!("直播间未开播"),
        _ => bail!("直播间状态异常: status={status}"),
    }

    let stream_url = data
        .get("stream_url")
        .ok_or_else(|| anyhow::anyhow!("缺少 stream_url"))?;

    if let Some(pull_datas) = stream_url.get("pull_datas").and_then(Value::as_object) {
        if let Some(first) = pull_datas.values().next() {
            if let Some(s) = first.get("stream_data").and_then(Value::as_str) {
                let parsed: Value = serde_json::from_str(s)?;
                if let Some(flv) = parsed
                    .pointer("/data/origin/main/flv")
                    .and_then(Value::as_str)
                {
                    return Ok(flv.to_string());
                }
            }
        }
    }

    if let Some(s) = stream_url
        .pointer("/live_core_sdk_data/pull_data/stream_data")
        .and_then(Value::as_str)
    {
        let parsed: Value = serde_json::from_str(s)?;
        if let Some(flv) = parsed
            .pointer("/data/origin/main/flv")
            .and_then(Value::as_str)
        {
            return Ok(flv.to_string());
        }
    }

    bail!("未找到抖音 FLV 流地址")
}
