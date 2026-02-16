-- DDL for single `profiles` table: immediate-profile creation, OTP fields, verification flag.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS profiles (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  email TEXT NOT NULL UNIQUE,
  phone TEXT NOT NULL,
  first_name TEXT NOT NULL,
  last_name TEXT NOT NULL,
  university TEXT NOT NULL,
  role TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  otp_hash TEXT,
  otp_expires_at TIMESTAMP WITH TIME ZONE,
  otp_attempts INTEGER DEFAULT 0,
  otp_last_sent_at TIMESTAMP WITH TIME ZONE,
  is_verified BOOLEAN DEFAULT FALSE,
  verified_at TIMESTAMP WITH TIME ZONE,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT now()
);

-- Index on email is provided by UNIQUE constraint; add an index on phone for quick lookup
CREATE INDEX IF NOT EXISTS idx_profiles_phone ON profiles (phone);

-- Cleanup helper example: delete unverified profiles older than 24 hours
-- You can run this as a scheduled job (cron, Cloud Scheduler, or a DB job)
-- DELETE FROM profiles WHERE is_verified = FALSE AND created_at < now() - interval '24 hours';
