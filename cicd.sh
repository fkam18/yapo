#!/bin/bash
./test_baseline.sh && ./deploy.sh || echo "TESTS FAILED – DO NOT RELEASE"
