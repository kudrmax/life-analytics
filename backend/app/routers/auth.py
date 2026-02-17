"""
Authentication endpoints: register, login, user info.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from app.database import get_db
from app.schemas import UserRegister, UserLogin, TokenResponse, UserOut
from app.auth import hash_password, verify_password, create_access_token, get_current_user
from app.seed import DEFAULT_METRICS
import json

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse)
async def register(data: UserRegister, db=Depends(get_db)):
    """
    Register a new user.

    - Validates username uniqueness
    - Hashes password
    - Creates user in database
    - Seeds default metrics for new user
    - Returns JWT access token
    """
    # Validate password length
    if len(data.password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Password must be at least 8 characters"
        )

    # Validate username format (3-30 alphanumeric/underscore)
    if not data.username or len(data.username) < 3 or len(data.username) > 30:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Username must be 3-30 characters"
        )

    # Check if username already exists
    cursor = await db.execute(
        "SELECT id FROM users WHERE username = ?",
        (data.username,)
    )
    existing_user = await cursor.fetchone()
    if existing_user:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists"
        )

    # Hash password
    password_hash = hash_password(data.password)

    # Create user
    cursor = await db.execute(
        "INSERT INTO users (username, password_hash) VALUES (?, ?)",
        (data.username, password_hash)
    )
    await db.commit()
    user_id = cursor.lastrowid

    # Seed default metrics for new user
    for metric in DEFAULT_METRICS:
        await db.execute(
            """
            INSERT INTO metric_configs (id, name, category, type, frequency, source, config_json, enabled, sort_order, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                metric["id"],
                metric["name"],
                metric.get("category", ""),
                metric["type"],
                metric.get("frequency", "daily"),
                metric.get("source", "manual"),
                json.dumps(metric.get("config", {})),
                1 if metric.get("enabled", True) else 0,
                metric.get("sort_order", 0),
                user_id
            )
        )
    await db.commit()

    # Generate access token
    access_token = create_access_token(user_id, data.username)

    return TokenResponse(
        access_token=access_token,
        username=data.username
    )


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db=Depends(get_db)):
    """
    Login with username and password.

    - Verifies credentials
    - Returns JWT access token
    """
    # Find user by username
    cursor = await db.execute(
        "SELECT id, username, password_hash FROM users WHERE username = ?",
        (data.username,)
    )
    user = await cursor.fetchone()

    if not user or not verify_password(data.password, user[2]):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password"
        )

    # Generate access token
    access_token = create_access_token(user[0], user[1])

    return TokenResponse(
        access_token=access_token,
        username=user[1]
    )


@router.get("/me", response_model=UserOut)
async def get_current_user_info(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    """
    Get current authenticated user information.
    """
    cursor = await db.execute(
        "SELECT id, username, created_at FROM users WHERE id = ?",
        (current_user["id"],)
    )
    user = await cursor.fetchone()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return UserOut(
        id=user[0],
        username=user[1],
        created_at=user[2]
    )
