//
// INTEL CONFIDENTIAL
//
// Copyright 2013-2015 Intel Corporation All Rights Reserved.
//
// The source code contained or described herein and all documents related
// to the source code ("Material") are owned by Intel Corporation or its
// suppliers or licensors. Title to the Material remains with Intel Corporation
// or its suppliers and licensors. The Material contains trade secrets and
// proprietary and confidential information of Intel or its suppliers and
// licensors. The Material is protected by worldwide copyright and trade secret
// laws and treaty provisions. No part of the Material may be used, copied,
// reproduced, modified, published, uploaded, posted, transmitted, distributed,
// or disclosed in any way without Intel's prior express written permission.
//
// No license under any patent, copyright, trade secret or other intellectual
// property right is granted to or conferred upon you by disclosure or delivery
// of the Materials, either expressly, by implication, inducement, estoppel or
// otherwise. Any license under such intellectual property rights must be
// express and approved by Intel in writing.


'use strict';

var primus = require('./primus');
var Primus = require('primus');
var multiplex = require('primus-multiplex');
var errorSerializer = require('bunyan/lib/bunyan').stdSerializers.err;
var MultiplexSpark = require('primus-multiplex/lib/server/spark');
var primusServerWriteFactory = require('./primus-server-write');
var primusServerWrite = primusServerWriteFactory(errorSerializer, MultiplexSpark);
var Emitter = require('primus-emitter');

module.exports = function () {
  var instance = primus(Primus, { primusPort: 8889 }, multiplex, primusServerWrite, Emitter);

  var lib = instance.library();

  instance.end();

  return lib;
};