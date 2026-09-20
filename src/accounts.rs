use std::path::{Path, PathBuf};

use anyhow::Result;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize, Default)]
pub struct Account {
    pub access_key: String,
    pub uid: String,
    #[serde(default)]
    pub name: String,
    #[serde(rename = "type", default)]
    pub type_: String,
    #[serde(default)]
    pub note: String,
    #[serde(default)]
    pub mid: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AccountStore {
    #[serde(default)]
    pub auto_exit: bool,
    #[serde(default)]
    pub auto_login: bool,
    #[serde(default)]
    pub auto_start: bool,
    #[serde(default)]
    pub account: Vec<Account>,
    #[serde(default)]
    pub last_account: usize,
    #[serde(default)]
    pub num: usize,
}

impl Default for AccountStore {
    fn default() -> Self {
        Self {
            auto_exit: false,
            auto_login: false,
            auto_start: false,
            account: Vec::new(),
            last_account: 0,
            num: 0,
        }
    }
}

impl AccountStore {
    /// 默认路径可用 MHYSCAN_CONFIG 覆盖，否则为 ./Config/userinfo.json
    pub fn default_path() -> PathBuf {
        std::env::var("MHYSCAN_CONFIG")
            .map(PathBuf::from)
            .unwrap_or_else(|_| PathBuf::from("Config/userinfo.json"))
    }

    pub fn load(path: impl AsRef<Path>) -> Result<Self> {
        let path = path.as_ref();
        if path.exists() {
            let text = std::fs::read_to_string(path)?;
            Ok(serde_json::from_str(&text).unwrap_or_default())
        } else {
            Ok(Self::default())
        }
    }

    pub fn save(&self, path: impl AsRef<Path>) -> Result<()> {
        let path = path.as_ref();
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent)?;
        }
        std::fs::write(path, serde_json::to_string_pretty(self)?)?;
        Ok(())
    }

    pub fn add_account(
        &mut self,
        name: &str,
        token: &str,
        uid: &str,
        mid: &str,
        type_: &str,
    ) -> bool {
        if self.account.iter().any(|a| a.uid == uid) {
            return false;
        }
        self.account.push(Account {
            access_key: token.to_string(),
            uid: uid.to_string(),
            name: name.to_string(),
            type_: type_.to_string(),
            note: String::new(),
            mid: mid.to_string(),
        });
        self.num = self.account.len();
        true
    }
}
