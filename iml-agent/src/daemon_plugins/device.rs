// Copyright (c) 2020 DDN. All rights reserved.
// Use of this source code is governed by a MIT-style
// license that can be found in the LICENSE file.

use crate::{
    agent_error::ImlAgentError,
    daemon_plugins::{DaemonPlugin, Output},
};
use async_trait::async_trait;
use futures::{
    future, lock::Mutex, Future, FutureExt, Stream, StreamExt, TryFutureExt, TryStreamExt,
};
use std::{io, pin::Pin, sync::Arc};
use stream_cancel::{Trigger, Tripwire};
use tokio::{io::AsyncWriteExt, net::UnixStream};
use tokio_util::codec::{FramedRead, LinesCodec};
use treediff::diff;

/// Opens a persistent stream to device scanner.
fn device_stream() -> impl Stream<Item = Result<String, ImlAgentError>> {
    UnixStream::connect("/var/run/device-scanner.sock")
        .err_into()
        .and_then(|mut conn| async {
            conn.write_all(b"\"Stream\"\n")
                .err_into::<ImlAgentError>()
                .await?;

            Ok(conn)
        })
        .map_ok(|c| FramedRead::new(c, LinesCodec::new()).err_into())
        .try_flatten_stream()
}

#[derive(Eq, PartialEq)]
enum State {
    Pending,
    Sent,
}

pub fn create() -> impl DaemonPlugin {
    Devices {
        trigger: None,
        state: Arc::new(Mutex::new((None, None, State::Sent))),
    }
}

pub enum Update {
    Initial(Output),
    Patch(()),
}

#[derive(Debug)]
pub struct Devices {
    trigger: Option<Trigger>,
    state: Arc<Mutex<(Output, Output, State)>>,
}

#[async_trait]
impl DaemonPlugin for Devices {
    fn start_session(
        &mut self,
    ) -> Pin<Box<dyn Future<Output = Result<Output, ImlAgentError>> + Send>> {
        let (trigger, tripwire) = Tripwire::new();

        self.trigger = Some(trigger);

        let fut = device_stream()
            .boxed()
            .and_then(|x| future::ready(serde_json::from_str(&x)).err_into())
            .into_future();

        let state = Arc::clone(&self.state);

        Box::pin(async move {
            let (x, s) = fut.await;

            let x: Output = match x {
                Some(x) => x,
                None => {
                    return Err(ImlAgentError::Io(io::Error::new(
                        io::ErrorKind::ConnectionAborted,
                        "Device scanner connection aborted before any data was sent",
                    )))
                }
            }?;

            {
                let mut lock = state.lock().await;

                lock.1 = x.clone();
            }

            tokio::spawn(
                s.take_until(tripwire)
                    .try_for_each(move |x| {
                        let state = Arc::clone(&state);

                        async move {
                            let mut lock = state.lock().await;

                            if lock.1 != x {
                                tracing::debug!("marking pending (is none: {}) ", x.is_none());

                                lock.1 = x;
                                lock.2 = State::Pending;
                            }

                            Ok(())
                        }
                    })
                    .map(|x| {
                        if let Err(e) = x {
                            tracing::error!("Error processing device output: {}", e);
                        }
                    }),
            );

            Ok(x)
        })
    }
    fn update_session(
        &self,
    ) -> Pin<Box<dyn Future<Output = Result<Output, ImlAgentError>> + Send>> {
        let state = Arc::clone(&self.state);

        async move {
            let mut lock = state.lock().await;

            if lock.2 == State::Pending {
                tracing::debug!("Sending new value");
                lock.2 = State::Sent;

                let old = &lock.0;
                let new = &lock.1;

                old.as_ref().map(|old| {
                    new.as_ref().map(|new| {
                        let mut d = my::Recorder::default();
                        diff(old, new, &mut d);
                        let serialized_recorder = serde_json::to_value(&d).unwrap();
                    })
                });

                Ok(lock.1.clone())
            } else {
                Ok(None)
            }
        }
        .boxed()
    }
    async fn teardown(&mut self) -> Result<(), ImlAgentError> {
        self.trigger.take();

        Ok(())
    }
}

mod my {
    use serde::{Deserialize, Serialize};
    use treediff::Delegate;

    #[derive(Debug, PartialEq, Deserialize, Serialize)]
    pub enum ChangeType<K, V> {
        Removed(Vec<K>, V),
        Added(Vec<K>, V),
        Unchanged(Vec<K>, V),
        Modified(Vec<K>, V, V),
    }

    #[derive(Debug, PartialEq, Deserialize, Serialize)]
    pub struct Recorder<K, V> {
        cursor: Vec<K>,
        pub calls: Vec<ChangeType<K, V>>,
    }

    impl<K, V> Default for Recorder<K, V> {
        fn default() -> Self {
            Recorder {
                cursor: Vec::new(),
                calls: Vec::new(),
            }
        }
    }

    fn mk<K>(c: &[K], k: Option<&K>) -> Vec<K>
    where
        K: Clone,
    {
        let mut c = Vec::from(c);
        match k {
            Some(k) => {
                c.push(k.clone());
                c
            }
            None => c,
        }
    }

    impl<'a, K, V> Delegate<'a, K, V> for Recorder<K, V>
    where
        K: Clone,
        V: Clone,
    {
        fn push(&mut self, k: &K) {
            self.cursor.push(k.clone())
        }
        fn pop(&mut self) {
            self.cursor.pop();
        }
        fn removed<'b>(&mut self, k: &'b K, v: &'a V) {
            self.calls
                .push(ChangeType::Removed(mk(&self.cursor, Some(k)), v.clone()));
        }
        fn added<'b>(&mut self, k: &'b K, v: &'a V) {
            self.calls
                .push(ChangeType::Added(mk(&self.cursor, Some(k)), v.clone()));
        }
        fn unchanged<'b>(&mut self, v: &'a V) {
            self.calls
                .push(ChangeType::Unchanged(self.cursor.clone(), v.clone()));
        }
        fn modified<'b>(&mut self, v1: &'a V, v2: &'a V) {
            self.calls.push(ChangeType::Modified(
                mk(&self.cursor, None),
                v1.clone(),
                v2.clone(),
            ));
        }
    }
}
