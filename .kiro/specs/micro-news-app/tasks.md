# Tasks

## Task List

- [ ] 1 Project Setup and Configuration
  - [ ] 1.1 Initialize Flask app with application factory pattern (`create_app`)
  - [ ] 1.2 Configure SQLAlchemy with SQLite (dev) and PostgreSQL (prod) via `DATABASE_URL` env var
  - [ ] 1.3 Register `admin_app` and `user_app` blueprints
  - [ ] 1.4 Configure Flask-Login with separate session protection for admin and user
  - [ ] 1.5 Configure APScheduler and attach to app context
  - [ ] 1.6 Set up project structure: `app/`, `app/admin/`, `app/user/`, `app/models/`, `app/services/`, `app/agents/`, `tests/`
  - [ ] 1.7 Create `requirements.txt` with all dependencies (Flask, SQLAlchemy, Flask-Login, APScheduler, CrewAI, Hypothesis, Bootstrap 5 via CDN reference)

- [ ] 2 Database Models
  - [ ] 2.1 Implement `Admin` model with `id`, `username` (unique), `password_hash`, `created_at`
  - [ ] 2.2 Implement `User` model with `id`, `email` (unique), `password_hash`, `name`, `birthday`, `preferred_delivery_time`, `is_active`, `email_verified`, `created_at`
  - [ ] 2.3 Implement `Category` model with `id`, `name` (unique, case-insensitive index), `created_at`
  - [ ] 2.4 Implement `Snippet` model with `id`, `category_id` (FK), `headline`, `body`, `source_url`, `collection_date`, `created_at`
  - [ ] 2.5 Implement `Subscription` model with `id`, `user_id` (FK), `category_id` (FK), `subscribed_at`; unique constraint on `(user_id, category_id)`
  - [ ] 2.6 Implement `UserSnippet` model with `id`, `user_id` (FK), `snippet_id` (FK), `is_read`, `is_deleted`, `delivered_at`, `read_at`; unique constraint on `(user_id, snippet_id)`
  - [ ] 2.7 Implement `CollectionLog` model with `id`, `run_at`, `total_snippets`, `categories_processed`, `categories_failed`, `failure_details` (JSON text)
  - [ ] 2.8 Implement `PasswordResetToken` model with `id`, `user_id` (FK), `token` (unique), `expires_at`, `used`
  - [ ] 2.9 Implement `EmailVerificationToken` model with `id`, `user_id` (FK), `token` (unique), `expires_at`, `used`
  - [ ] 2.10 Create Alembic migration for initial schema

- [ ] 3 Admin Authentication
  - [ ] 3.1 Implement admin login route (`GET /admin/login`, `POST /admin/login`) with credential validation
  - [ ] 3.2 Implement admin logout route (`POST /admin/logout`)
  - [ ] 3.3 Implement `@admin_required` decorator to protect all admin routes (redirect to `/admin/login` if not authenticated)
  - [ ] 3.4 Configure admin session timeout at 60 minutes of inactivity
  - [ ] 3.5 Implement rate limiting: block source IP for 15 minutes after 5 consecutive failed attempts within 10 minutes (use Flask-Limiter or in-memory store)
  - [ ] 3.6 Implement admin account bootstrapping: on app startup, if no Admin exists, read `ADMIN_USERNAME` and `ADMIN_PASSWORD` env vars and create the account; halt with `SystemExit(1)` if vars are missing

- [ ] 4 Admin Category Management
  - [ ] 4.1 Implement admin dashboard route (`GET /admin/dashboard`) showing category count and today's collection stats
  - [ ] 4.2 Implement category list route (`GET /admin/categories`) with alphabetical sort and pagination (20 per page)
  - [ ] 4.3 Implement category creation route (`POST /admin/categories/new`) with case-insensitive duplicate check
  - [ ] 4.4 Implement category deletion route (`POST /admin/categories/<id>/delete`) with pre-deletion affected-user count confirmation
  - [ ] 4.5 Implement cascade deletion: when a category is deleted, remove all associated Snippets, UserSnippets, and Subscriptions
  - [ ] 4.6 Implement collection log view route (`GET /admin/collection-log`) with paginated run history

- [ ] 5 Email Validator and Password Services
  - [ ] 5.1 Implement `Email_Validator.validate_format(email)` using RFC 5322 regex
  - [ ] 5.2 Implement `Email_Validator.validate_existence(email)` using DNS MX record lookup
  - [ ] 5.3 Implement password policy validator: min 8 chars, at least one uppercase, one lowercase, one digit
  - [ ] 5.4 Implement `Password_Reset_Service.send_reset_link(user)`: generate secure token, persist `PasswordResetToken` with 1-hour expiry, send email via SMTP
  - [ ] 5.5 Implement `Password_Reset_Service.validate_token(token)`: return User if token exists, is not used, and not expired; else return None
  - [ ] 5.6 Implement `Password_Reset_Service.consume_token(token, new_password)`: hash and save new password, set `used=True`
  - [ ] 5.7 Implement email verification token generation and sending on registration (24-hour expiry)
  - [ ] 5.8 Implement email verification token consumption route (`GET /verify/<token>`)

- [ ] 6 User Registration and Authentication
  - [ ] 6.1 Implement user registration route (`GET /register`, `POST /register`) using Email_Validator and password policy
  - [ ] 6.2 Implement user login route (`GET /login`, `POST /login`) with generic error messages
  - [ ] 6.3 Implement user logout route (`POST /logout`)
  - [ ] 6.4 Implement `@login_required` decorator for user routes (redirect to `/login`)
  - [ ] 6.5 Configure user session timeout at 120 minutes of inactivity

- [ ] 7 User Profile Management
  - [ ] 7.1 Implement profile view/update route (`GET /profile`, `POST /profile`) for name, birthday, preferred_delivery_time
  - [ ] 7.2 Validate birthday: must be a valid calendar date in the past
  - [ ] 7.3 On preferred_delivery_time update, reschedule the user's APScheduler delivery job
  - [ ] 7.4 Implement change-password route (`POST /profile/change-password`) that triggers `Password_Reset_Service.send_reset_link`
  - [ ] 7.5 Implement password reset form route (`GET /reset-password/<token>`, `POST /reset-password/<token>`)

- [ ] 8 Subscription Management
  - [ ] 8.1 Implement subscriptions list route (`GET /subscriptions`) showing all categories with subscription status
  - [ ] 8.2 Implement subscribe route (`POST /subscriptions/<category_id>/subscribe`)
  - [ ] 8.3 Implement unsubscribe route (`POST /subscriptions/<category_id>/unsubscribe`)
  - [ ] 8.4 Display prompt on subscriptions page when user has no active subscriptions

- [ ] 9 News Collection Agent
  - [ ] 9.1 Implement `News_Agent` using CrewAI with a search tool (SerperDev or DuckDuckGo) and a summarization task
  - [ ] 9.2 Implement `run_news_collection()` job: iterate over all categories, run crew per category, parse output into `Snippet` records (max 10 per category), persist to DB
  - [ ] 9.3 Implement per-category error handling: catch exceptions, log to `CollectionLog.failure_details`, continue to next category
  - [ ] 9.4 Implement `CollectionLog` creation at end of each run with `run_at`, `total_snippets`, `categories_processed`, `categories_failed`
  - [ ] 9.5 Schedule `run_news_collection` with APScheduler at 09:00 IST (03:30 UTC) daily via `CronTrigger`

- [ ] 10 Delivery Service
  - [ ] 10.1 Implement `Delivery_Service.deliver_for_user(user_id)`: query undelivered UserSnippet rows for user's subscribed categories with today's collection_date, set `delivered_at=now()`, return count
  - [ ] 10.2 Implement `schedule_delivery_job(user)`: convert user's preferred_delivery_time from IST to UTC, add/replace APScheduler cron job keyed by `delivery_{user.id}`
  - [ ] 10.3 Default delivery time to 10:00 IST (04:30 UTC) when `preferred_delivery_time` is null
  - [ ] 10.4 On app startup, reschedule delivery jobs for all existing users with a preferred_delivery_time set
  - [ ] 10.5 When a new snippet is collected, create `UserSnippet` rows (with `delivered_at=null`) for all users subscribed to that category

- [ ] 11 News Feed UI
  - [ ] 11.1 Implement user dashboard route (`GET /dashboard`) showing unread count and today's delivered snippets summary
  - [ ] 11.2 Implement feed route (`GET /feed`) showing delivered snippets grouped by category, unread before read
  - [ ] 11.3 Implement mark-as-read route (`POST /feed/snippets/<id>/read`): set `UserSnippet.is_read=True`, `read_at=now()`
  - [ ] 11.4 Implement delete-from-feed route (`POST /feed/snippets/<id>/delete`): set `UserSnippet.is_deleted=True`
  - [ ] 11.5 Display prompt on dashboard/feed when user has no subscriptions

- [ ] 12 Frontend Templates (Bootstrap 5)
  - [ ] 12.1 Create base templates for admin and user apps with Bootstrap 5 CDN, responsive navbar, and flash message display
  - [ ] 12.2 Create admin templates: login, dashboard, category list, category delete confirmation, collection log
  - [ ] 12.3 Create user templates: register, login, dashboard, feed, profile, subscriptions, password reset
  - [ ] 12.4 Ensure all interactive elements have minimum 44x44px touch targets on mobile viewports
  - [ ] 12.5 Implement mobile-optimized navigation (Bootstrap navbar collapse) for viewports < 768px

- [ ] 13 Property-Based Tests
  - [ ] 13.1 Write property test for Property 1: valid credentials authenticate users
  - [ ] 13.2 Write property test for Property 2: invalid credentials are rejected
  - [ ] 13.3 Write property test for Property 3: unauthenticated requests are redirected
  - [ ] 13.4 Write property test for Property 4: inactive sessions are invalidated
  - [ ] 13.5 Write property test for Property 5: rate limiting blocks excessive failed logins
  - [ ] 13.6 Write property test for Property 6: category creation round-trip
  - [ ] 13.7 Write property test for Property 7: duplicate category names are rejected
  - [ ] 13.8 Write property test for Property 8: category deletion cascades to snippets
  - [ ] 13.9 Write property test for Property 9: affected-user count is accurate before deletion
  - [ ] 13.10 Write property test for Property 10: category list is alphabetically sorted
  - [ ] 13.11 Write property test for Property 11: snippet word count invariant
  - [ ] 13.12 Write property test for Property 12: snippets are associated with their category
  - [ ] 13.13 Write property test for Property 13: collection failure log completeness
  - [ ] 13.14 Write property test for Property 14: collection log records run metadata
  - [ ] 13.15 Write property test for Property 15: snippet count per category per run is bounded
  - [ ] 13.16 Write property test for Property 16: registration creates a user account
  - [ ] 13.17 Write property test for Property 17: invalid email formats are rejected
  - [ ] 13.18 Write property test for Property 18: duplicate email registration is rejected
  - [ ] 13.19 Write property test for Property 19: weak passwords are rejected
  - [ ] 13.20 Write property test for Property 20: email verification token round-trip
  - [ ] 13.21 Write property test for Property 21: expired tokens are rejected
  - [ ] 13.22 Write property test for Property 22: profile fields persist correctly
  - [ ] 13.23 Write property test for Property 23: birthday must be a past date
  - [ ] 13.24 Write property test for Property 24: profile page displays all fields
  - [ ] 13.25 Write property test for Property 25: password reset token is created on request
  - [ ] 13.26 Write property test for Property 26: password reset token consumption updates password
  - [ ] 13.27 Write property test for Property 27: subscribe/unsubscribe round-trip
  - [ ] 13.28 Write property test for Property 28: category list reflects subscription status
  - [ ] 13.29 Write property test for Property 29: delivery sets delivered_at on all eligible snippets
  - [ ] 13.30 Write property test for Property 30: no delivery when no snippets available
  - [ ] 13.31 Write property test for Property 31: mark-as-read is user-scoped
  - [ ] 13.32 Write property test for Property 32: snippet deletion is user-scoped
  - [ ] 13.33 Write property test for Property 33: feed ordering puts unread before read
  - [ ] 13.34 Write property test for Property 34: unread count matches database state
  - [ ] 13.35 Write property test for Property 35: bootstrap is idempotent when admin exists

- [ ] 14 Unit Tests
  - [ ] 14.1 Test admin bootstrapping: env vars present + no admin → creates admin
  - [ ] 14.2 Test admin bootstrapping: env vars missing + no admin → SystemExit(1)
  - [ ] 14.3 Test admin bootstrapping: admin already exists → no-op
  - [ ] 14.4 Test default delivery time is 10:00 IST when preferred_delivery_time is null
  - [ ] 14.5 Test CollectionLog creation with mixed success/failure categories
  - [ ] 14.6 Test token expiry boundary: token expiring exactly at current time is rejected
  - [ ] 14.7 Test no-subscription prompt appears when user has zero subscriptions
  - [ ] 14.8 Test default delivery time (10:00 IST) when user has no preferred_delivery_time set
