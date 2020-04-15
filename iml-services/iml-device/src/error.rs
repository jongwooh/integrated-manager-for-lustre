// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

use iml_orm::tokio_diesel;
use iml_service_queue::service_queue::ImlServiceQueueError;
use r2d2;
use thiserror::Error;
use warp::reject;

#[derive(Error, Debug)]
pub enum ImlDeviceError {
    #[error(transparent)]
    ImlServiceQueueError(#[from] ImlServiceQueueError),
    #[error(transparent)]
    R2d2Error(#[from] r2d2::Error),
    #[error(transparent)]
    TokioDieselAsyncError(#[from] tokio_diesel::AsyncError),
}

impl reject::Reject for ImlDeviceError {}
