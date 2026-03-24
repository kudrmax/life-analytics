"""Authentication endpoints: register, login, user info."""
from fastapi import APIRouter, Depends, HTTPException, status

from app.database import get_db
from app.schemas import UserRegister, UserLogin, TokenResponse, UserOut, PrivacyModeUpdate
from app.auth import get_current_user
from app.repositories.auth_repository import AuthRepository
from app.services.auth_service import AuthService, AuthenticationError

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _service(db) -> AuthService:
    return AuthService(AuthRepository(db))


@router.post("/register", response_model=TokenResponse)
async def register(data: UserRegister, db=Depends(get_db)):
    return await _service(db).register(data.username, data.password)


@router.post("/login", response_model=TokenResponse)
async def login(data: UserLogin, db=Depends(get_db)):
    try:
        return await _service(db).login(data.username, data.password)
    except AuthenticationError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid username or password")


@router.get("/me", response_model=UserOut)
async def get_current_user_info(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    return await _service(db).get_user_info(current_user["id"])


@router.get("/privacy-mode")
async def get_privacy_mode_endpoint(current_user: dict = Depends(get_current_user), db=Depends(get_db)):
    privacy_mode = await _service(db).get_privacy_mode(current_user["id"])
    return {"privacy_mode": privacy_mode}


@router.put("/privacy-mode")
async def set_privacy_mode(body: PrivacyModeUpdate, db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    result = await _service(db).set_privacy_mode(current_user["id"], body.enabled)
    return {"privacy_mode": result}


@router.delete("/account", status_code=204)
async def delete_account(db=Depends(get_db), current_user: dict = Depends(get_current_user)):
    await _service(db).delete_account(current_user["id"])
