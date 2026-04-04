from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import FavoritePlace, Place
from app.schemas import FavoritePlaceCopyRequest, FavoritePlaceCreate, FavoritePlaceOut

router = APIRouter(prefix="/favorite-places", tags=["favorite-places"])


def _get_favorite_or_404(favorite_id: int, db: Session) -> FavoritePlace:
    fav = db.get(FavoritePlace, favorite_id)
    if fav is None:
        raise HTTPException(status_code=404, detail="Favorite place not found")
    return fav


@router.post("", response_model=FavoritePlaceOut, status_code=status.HTTP_201_CREATED)
def create_favorite_place(payload: FavoritePlaceCreate, db: Session = Depends(get_db)):
    fav = FavoritePlace(**payload.model_dump())
    db.add(fav)
    db.commit()
    db.refresh(fav)
    return fav


@router.post("/copy-from-itinerary", response_model=FavoritePlaceOut, status_code=status.HTTP_201_CREATED)
def copy_place_to_favorites(payload: FavoritePlaceCopyRequest, db: Session = Depends(get_db)):
    """Copy a place from a day itinerary into the global favorites library."""
    place = db.get(Place, payload.place_id)
    if place is None:
        raise HTTPException(status_code=404, detail="Place not found")
    fav = FavoritePlace(
        name=place.name,
        category=place.category,
        address=place.address,
        estimated_cost=place.estimated_cost,
        ai_reason=place.ai_reason,
        notes=payload.notes,
    )
    db.add(fav)
    db.commit()
    db.refresh(fav)
    return fav


@router.get("", response_model=list[FavoritePlaceOut])
def list_favorite_places(db: Session = Depends(get_db)):
    return db.query(FavoritePlace).order_by(FavoritePlace.id).all()


@router.get("/{favorite_id}", response_model=FavoritePlaceOut)
def get_favorite_place(favorite_id: int, db: Session = Depends(get_db)):
    return _get_favorite_or_404(favorite_id, db)


@router.delete("/{favorite_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_favorite_place(favorite_id: int, db: Session = Depends(get_db)):
    fav = _get_favorite_or_404(favorite_id, db)
    db.delete(fav)
    db.commit()
