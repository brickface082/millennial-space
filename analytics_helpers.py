"""Aggregate site metrics for the admin dashboard."""
from datetime import datetime, timedelta

from sqlalchemy import func, distinct


def build_metrics_report():
    from app import (
        db,
        User,
        Post,
        Bulletin,
        DirectMessage,
        Comment,
        PhotoAlbum,
        Photo,
        PhotoMontage,
        Poll,
        PollVote,
        SpotListing,
        CornerEvent,
        CrewRequest,
        JournalEntry,
        Invite,
        InviteReferral,
        AnalyticsEvent,
        ProfileView,
    )

    now = datetime.utcnow()
    day_7 = now - timedelta(days=7)
    day_30 = now - timedelta(days=30)

    total_users = User.query.count() or 0
    signups_7d = User.query.filter(User.joined_at >= day_7).count()
    signups_30d = User.query.filter(User.joined_at >= day_30).count()
    referred_signups = InviteReferral.query.count()
    organic_signups = max(0, total_users - referred_signups)

    active_7d = User.query.filter(User.last_seen >= day_7).count()
    active_30d = User.query.filter(User.last_seen >= day_30).count()

    logins_7d = AnalyticsEvent.query.filter(
        AnalyticsEvent.event_type == "login",
        AnalyticsEvent.created_at >= day_7,
    ).count()

    profile_views_total = db.session.query(func.coalesce(func.sum(User.profile_views), 0)).scalar() or 0
    profile_views_7d = ProfileView.query.filter(ProfileView.viewed_at >= day_7).count()

    def distinct_users(model, col):
        return db.session.query(func.count(distinct(col))).scalar() or 0

    def total_rows(model):
        return model.query.count()

    feature_defs = [
        ("Mail (sent)", "mail", lambda: distinct_users(DirectMessage, DirectMessage.from_id), lambda: total_rows(DirectMessage)),
        ("Profile comments", "comments", lambda: distinct_users(Comment, Comment.author_id), lambda: total_rows(Comment)),
        ("Blurbs / posts", "posts", lambda: distinct_users(Post, Post.user_id), lambda: total_rows(Post)),
        ("Bulletins", "bulletins", lambda: distinct_users(Bulletin, Bulletin.user_id), lambda: total_rows(Bulletin)),
        ("Photo albums", "albums", lambda: distinct_users(PhotoAlbum, PhotoAlbum.user_id), lambda: total_rows(PhotoAlbum)),
        ("Photos uploaded", "photos", lambda: _photo_users(), lambda: total_rows(Photo)),
        ("Photo montages", "montage", lambda: distinct_users(PhotoMontage, PhotoMontage.user_id), lambda: total_rows(PhotoMontage)),
        ("Polls created", "polls", lambda: distinct_users(Poll, Poll.creator_id), lambda: total_rows(Poll)),
        ("Poll votes", "poll_votes", lambda: distinct_users(PollVote, PollVote.user_id), lambda: total_rows(PollVote)),
        ("The Spot listings", "spot_listings", lambda: distinct_users(SpotListing, SpotListing.user_id), lambda: total_rows(SpotListing)),
        ("The Spot events", "spot_events", lambda: distinct_users(CornerEvent, CornerEvent.user_id), lambda: total_rows(CornerEvent)),
        ("Journal / blog", "journal", lambda: distinct_users(JournalEntry, JournalEntry.user_id), lambda: total_rows(JournalEntry)),
        ("Crew connections", "crew", lambda: _crew_users(), lambda: CrewRequest.query.filter_by(status="accepted").count()),
        ("Top 8 configured", "top8", lambda: User.query.filter(User.top8 != "", User.top8.isnot(None)).count(), lambda: None),
        ("Profile song set", "profile_song", lambda: User.query.filter(User.profile_song != "", User.profile_song.isnot(None)).count(), lambda: None),
        ("Custom CSS", "custom_css", lambda: User.query.filter(User.custom_css != "", User.custom_css.isnot(None)).count(), lambda: None),
        ("Invite links created", "invites", lambda: distinct_users(Invite, Invite.created_by), lambda: total_rows(Invite)),
        ("Update emails opt-in", "updates_opt_in", lambda: User.query.filter_by(updates_opt_in=True).count(), lambda: None),
    ]

    def _crew_users():
        accepted = CrewRequest.query.filter_by(status="accepted").all()
        ids = set()
        for r in accepted:
            ids.add(r.from_id)
            ids.add(r.to_id)
        return len(ids)

    def _photo_users():
        return (
            db.session.query(func.count(distinct(PhotoAlbum.user_id)))
            .join(Photo, Photo.album_id == PhotoAlbum.id)
            .scalar()
            or 0
        )

    features = []
    for label, key, users_fn, actions_fn in feature_defs:
        users = users_fn()
        actions = actions_fn() if actions_fn else None
        pct = round(100 * users / total_users, 1) if total_users else 0
        features.append({
            "label": label,
            "key": key,
            "users": users,
            "actions": actions,
            "pct": pct,
        })

    features.sort(key=lambda f: (f["users"], f["actions"] or 0), reverse=True)
    least_used = sorted(features, key=lambda f: (f["users"], f["actions"] or 0))[:8]

    page_views_7d = (
        db.session.query(
            AnalyticsEvent.feature_key,
            func.count(AnalyticsEvent.id),
        )
        .filter(
            AnalyticsEvent.event_type == "page_view",
            AnalyticsEvent.created_at >= day_7,
        )
        .group_by(AnalyticsEvent.feature_key)
        .order_by(func.count(AnalyticsEvent.id).desc())
        .all()
    )

    nav_clicks_7d = (
        db.session.query(
            AnalyticsEvent.feature_key,
            func.count(AnalyticsEvent.id),
        )
        .filter(
            AnalyticsEvent.event_type == "nav_click",
            AnalyticsEvent.created_at >= day_7,
        )
        .group_by(AnalyticsEvent.feature_key)
        .order_by(func.count(AnalyticsEvent.id).desc())
        .limit(15)
        .all()
    )

    signups_by_day = (
        db.session.query(
            func.date(User.joined_at),
            func.count(User.id),
        )
        .filter(User.joined_at.isnot(None), User.joined_at >= day_30)
        .group_by(func.date(User.joined_at))
        .order_by(func.date(User.joined_at))
        .all()
    )

    recent_signups = (
        User.query.filter(User.joined_at.isnot(None))
        .order_by(User.joined_at.desc())
        .limit(15)
        .all()
    )

    events_7d = AnalyticsEvent.query.filter(AnalyticsEvent.created_at >= day_7).count()

    return {
        "generated_at": now,
        "overview": {
            "total_users": total_users,
            "signups_7d": signups_7d,
            "signups_30d": signups_30d,
            "organic_signups": organic_signups,
            "referred_signups": referred_signups,
            "active_7d": active_7d,
            "active_30d": active_30d,
            "logins_7d": logins_7d,
            "profile_views_total": int(profile_views_total),
            "profile_views_7d": profile_views_7d,
            "events_tracked_7d": events_7d,
        },
        "features": features,
        "least_used": least_used,
        "page_views_7d": [{"key": k, "count": c} for k, c in page_views_7d],
        "nav_clicks_7d": [{"key": k, "count": c} for k, c in nav_clicks_7d],
        "signups_by_day": [{"day": str(d), "count": c} for d, c in signups_by_day],
        "recent_signups": recent_signups,
    }