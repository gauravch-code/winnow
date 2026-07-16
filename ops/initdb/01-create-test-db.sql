-- Separate scratch DB for pytest so integration tests never touch the dev DB.
CREATE DATABASE winnow_test OWNER winnow;
