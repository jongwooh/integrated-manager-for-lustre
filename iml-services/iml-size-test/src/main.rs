// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

use futures::TryStreamExt;
use iml_orm::{tokio_diesel::AsyncError, ImlOrmError};
use iml_service_queue::service_queue::{consume_data, ImlServiceQueueError};
use serde::{Deserialize, Serialize};
use thiserror::Error;

#[derive(Error, Debug)]
pub enum ImlSizeTestError {
    #[error(transparent)]
    AsyncError(#[from] AsyncError),
    #[error(transparent)]
    ImlOrmError(#[from] ImlOrmError),
    #[error(transparent)]
    ImlServiceQueueError(#[from] ImlServiceQueueError),
    #[error(transparent)]
    SerdeJsonError(#[from] serde_json::Error),
}

#[tokio::main]
async fn main() -> Result<(), ImlSizeTestError> {
    iml_tracing::init();

    // let _addr = iml_manager_env::get_size_test_addr();

    tracing::info!("Server starting");

    #[derive(Deserialize, Serialize)]
    struct Datum {
        datum: [u64; 32],
    }

    let mut s = consume_data::<Vec<Datum>>("rust_agent_size_test_rx");

    while let Some((f, output)) = s.try_next().await? {
        tracing::info!("Received {} datums from {}", output.len(), f);
    }

    Ok(())
}
