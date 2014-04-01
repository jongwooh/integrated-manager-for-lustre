describe('Fs dashboard controller', function () {
  'use strict';

  beforeEach(module('dashboard', function ($provide) {
    $provide.value('streams', {
      fileSystemStream: jasmine.createSpy('fileSystemStream').andReturn({
        start: jasmine.createSpy('start')
      })
    });
  }, {
    dashboardPath: {
      getFsId: function () {
        return 1;
      }
    }
  }));

  var $scope, streams;

  beforeEach(inject(function ($controller, $rootScope, _streams_) {
    $scope = $rootScope.$new();
    streams = _streams_;

    $controller('FsDashboardCtrl', {
      $scope: $scope
    });
  }));

  it('should contain the expected charts', function () {
    expect($scope.dashboard.charts).toEqual([
      {name: 'iml/read-write-heat-map/assets/html/read-write-heat-map.html'},
      {name: 'iml/ost-balance/assets/html/ost-balance.html'},
      {name: 'iml/mdo/assets/html/mdo.html'},
      {name: 'iml/read-write-bandwidth/assets/html/read-write-bandwidth.html'},
      {name: 'iml/mds/assets/html/mds.html'},
      {name: 'iml/object-storage-servers/assets/html/object-storage-servers.html'}
    ]);
  });

  it('should the filesystem id to child charts', function () {
    expect($scope.params.qs.filesystem_id).toBe(1);
  });

  it('should setup the fileSystemStream', function () {
    expect(streams.fileSystemStream).toHaveBeenCalledOnceWith('dashboard.fs', $scope);
  });

  it('should start the fileSystemStream', function () {
    expect(streams.fileSystemStream.plan().start).toHaveBeenCalledOnceWith({
      id: 1,
      jsonMask: 'label,mgt(primary_server_name),mdts(primary_server_name),osts,bytes_total,bytes_free,\
files_free,files_total,client_count,immutable_state'
    });
  });
});