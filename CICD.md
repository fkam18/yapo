cd /home/fkam/apps/
git clone -b public-release git@github.com:fkam18/yapo.git yapo-public
cd /home/fkam/apps/yapo/
....
./test_baseline.sh
update release.txt
./deploy.sh
