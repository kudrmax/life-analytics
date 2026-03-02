"""
Authentication endpoints: register, login, user info.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from app.database import get_db
from app.schemas import UserRegister, UserLogin, TokenResponse, UserOut
from app.auth import hash_password, verify_password, create_access_token, get_current_user
from app.seed import DEFAULT_METRICS
from app.metric_helpers import seed_metrics_for_user

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
async def register(data: UserRegister, db=Depends(get_db)):
    if len(data.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters",
        )

    if not data.username or len(data.username) < 3 or len(data.username) > 30:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be 3-30 characters",
        )

    existing = await db.fetchval(
        "SELECT id FROM users WHERE username = $1", data.username
    )
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )

    password_hash = hash_password(data.password)

    async with db.transaction():
        user_id = await db.fetchval(
            "INSERT INTO users (username, password_hash) VALUES ($1, $2) RETURNING id",
            data.username, password_hash,
        )
        await seed_metrics_for_user(db, user_id, DEFAULT_METRICS)

    access_token = create_access_token(user_id, data.username)
    return TokenResponse(access_token=access_token, username=data.username)


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db=Depends(get_db)):
    user = await db.fetchrow(
        "SELECT id, username, password_hash FROM users WHERE username = $1",
        data.username,
    )

    if not user or not verify_password(data.password, user["password_hash"]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
        )

    access_token = create_access_token(user["id"], user["username"])
    return TokenResponse(access_token=access_token, username=user["username"])


@router.get("/me", response_model=UserOut)
async def get_current_user_info(
    current_user: dict = Depends(get_current_user), db=Depends(get_db)
):
    user = await db.fetchrow(
        "SELECT id, username, created_at FROM users WHERE id = $1",
        current_user["id"],
    )
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserOut(
        id=user["id"],
        username=user["username"],
        created_at=str(user["created_at"]),
    )
