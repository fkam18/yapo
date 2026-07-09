#!/bin/bash
./build.sh
#rm -rf /home/fkam/.ansible/cp/*
ansible-playbook -i /home/fkam/apps/yapo/docker/inventory.ini /home/fkam/apps/yapo/docker/deploy.yml
