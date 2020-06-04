// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

use crate::{
    agent_error::ImlAgentError,
    daemon_plugins::{DaemonPlugin, Output},
};
use async_trait::async_trait;
use futures::{Future, FutureExt, StreamExt};
use serde::{Deserialize, Serialize};
use std::pin::Pin;

pub fn create() -> impl DaemonPlugin {
    SizeTest {}
}

#[derive(Debug)]
struct SizeTest {}

#[derive(Deserialize, Serialize)]
struct Datum {
    datum: [u64; 32],
}

#[async_trait]
impl DaemonPlugin for SizeTest {
    fn start_session(
        &mut self,
    ) -> Pin<Box<dyn Future<Output = Result<Output, ImlAgentError>> + Send>> {
        async move {
            {
                let mut data = Vec::with_capacity(16384);
                for _ in 0..16384 {
                    data.push(Datum { datum: [0; 32] });
                }
                let serialized = serde_json::to_value(&data).unwrap();
                let string = serde_json::to_string(&data).unwrap();
                tracing::info!("Sending {} bytes (create_session)", string.len());
                Ok(Some(serialized))
            }
        }
        .boxed()
    }
    fn update_session(
        &self,
    ) -> Pin<Box<dyn Future<Output = Result<Output, ImlAgentError>> + Send>> {
        async move {
            let mut data = Vec::with_capacity(16384);
            for _ in 0..16384 {
                data.push(Datum { datum: [0; 32] });
            }
            let serialized = serde_json::to_value(&data).unwrap();
            let string = serde_json::to_string(&data).unwrap();
            tracing::info!("Sending {} bytes", string.len());
        Ok(Some(serialized))
        }
        .boxed()
    }
    async fn teardown(&mut self) -> Result<(), ImlAgentError> {
        Ok(())
    }
}
