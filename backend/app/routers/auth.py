"""
Authentication endpoints: register, login, user info.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from app.database import get_db
from app.schemas import UserRegister, UserLogin, TokenResponse, UserOut, PrivacyModeUpdate
from app.auth import hash_password, verify_password, create_access_token, get_current_user
from app.repositories.auth_repository import AuthRepository

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

    repo = AuthRepository(db)
    if await repo.username_exists(data.username):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already exists",
        )

    password_hash = hash_password(data.password)
    user_id = await repo.create_user(data.username, password_hash)

    access_token = create_access_token(user_id, data.username)
    return TokenResponse(access_token=access_token, username=data.username)


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db=Depends(get_db)):
    repo = AuthRepository(db)
    user = await repo.find_by_username(data.username)

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
    repo = AuthRepository(db)
    user = await repo.get_user_info(current_user["id"])
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return UserOut(
        id=user["id"],
        username=user["username"],
        created_at=str(user["created_at"]),
    )


@router.get("/privacy-mode")
async def get_privacy_mode_endpoint(
    current_user: dict = Depends(get_current_user),
    db=Depends(get_db),
):
    repo = AuthRepository(db)
    privacy_mode = await repo.get_privacy_mode(current_user["id"])
    return {"privacy_mode": privacy_mode}


@router.put("/privacy-mode")
async def set_privacy_mode(
    body: PrivacyModeUpdate,
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = AuthRepository(db)
    await repo.set_privacy_mode(current_user["id"], body.enabled)
    return {"privacy_mode": body.enabled}


@router.delete("/account", status_code=204)
async def delete_account(
    db=Depends(get_db),
    current_user: dict = Depends(get_current_user),
):
    repo = AuthRepository(db)
    await repo.delete_user(current_user["id"])
