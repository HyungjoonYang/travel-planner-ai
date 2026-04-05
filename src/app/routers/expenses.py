from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Expense, TravelPlan
from app.schemas import BudgetSummary, BulkExpenseResult, ExpenseCreate, ExpenseOut, ExpenseUpdate

router = APIRouter(prefix="/plans/{plan_id}/expenses", tags=["expenses"])


def _get_plan_or_404(plan_id: int, db: Session) -> TravelPlan:
    plan = db.get(TravelPlan, plan_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="Travel plan not found")
    return plan


def _get_expense_or_404(plan_id: int, expense_id: int, db: Session) -> Expense:
    expense = db.get(Expense, expense_id)
    if expense is None or expense.travel_plan_id != plan_id:
        raise HTTPException(status_code=404, detail="Expense not found")
    return expense


@router.post("", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(
    plan_id: int, payload: ExpenseCreate, db: Session = Depends(get_db)
):
    _get_plan_or_404(plan_id, db)
    expense = Expense(**payload.model_dump(), travel_plan_id=plan_id)
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.post("/bulk", response_model=BulkExpenseResult, status_code=status.HTTP_201_CREATED)
def bulk_create_expenses(
    plan_id: int,
    payload: list[ExpenseCreate],
    db: Session = Depends(get_db),
):
    if not payload:
        raise HTTPException(status_code=422, detail="Expense list must not be empty")
    _get_plan_or_404(plan_id, db)
    expenses = [
        Expense(**item.model_dump(), travel_plan_id=plan_id) for item in payload
    ]
    for expense in expenses:
        db.add(expense)
    db.commit()
    for expense in expenses:
        db.refresh(expense)
    return BulkExpenseResult(items=expenses, count=len(expenses))


@router.get("", response_model=list[ExpenseOut])
def list_expenses(plan_id: int, db: Session = Depends(get_db)):
    _get_plan_or_404(plan_id, db)
    return (
        db.query(Expense)
        .filter(Expense.travel_plan_id == plan_id)
        .order_by(Expense.id)
        .all()
    )


@router.get("/summary", response_model=BudgetSummary)
def get_budget_summary(plan_id: int, db: Session = Depends(get_db)):
    plan = _get_plan_or_404(plan_id, db)
    expenses = (
        db.query(Expense).filter(Expense.travel_plan_id == plan_id).all()
    )
    total_spent = sum(e.amount for e in expenses)
    by_category: dict[str, float] = {}
    for e in expenses:
        key = e.category or "other"
        by_category[key] = round(by_category.get(key, 0.0) + e.amount, 2)
    over_budget = total_spent > plan.budget
    overage_pct = round((total_spent - plan.budget) / plan.budget * 100, 2) if over_budget else 0.0
    return BudgetSummary(
        plan_id=plan_id,
        budget=plan.budget,
        total_spent=round(total_spent, 2),
        remaining=round(plan.budget - total_spent, 2),
        by_category=by_category,
        expense_count=len(expenses),
        over_budget=over_budget,
        overage_pct=overage_pct,
    )


@router.get("/{expense_id}", response_model=ExpenseOut)
def get_expense(plan_id: int, expense_id: int, db: Session = Depends(get_db)):
    _get_plan_or_404(plan_id, db)
    return _get_expense_or_404(plan_id, expense_id, db)


@router.patch("/{expense_id}", response_model=ExpenseOut)
def update_expense(
    plan_id: int,
    expense_id: int,
    payload: ExpenseUpdate,
    db: Session = Depends(get_db),
):
    _get_plan_or_404(plan_id, db)
    expense = _get_expense_or_404(plan_id, expense_id, db)
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(expense, field, value)
    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(
    plan_id: int, expense_id: int, db: Session = Depends(get_db)
):
    _get_plan_or_404(plan_id, db)
    expense = _get_expense_or_404(plan_id, expense_id, db)
    db.delete(expense)
    db.commit()
