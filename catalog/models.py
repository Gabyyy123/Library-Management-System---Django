from django.db import models
from django.contrib.auth.models import User
from datetime import date

class UserProfile(models.Model):
    ROLE_CHOICES = (('student', 'Student'), ('instructor', 'Instructor'), ('admin', 'Librarian'))
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='student')
    id_number = models.CharField(max_length=50, blank=True)
    # ADD THIS LINE BELOW
    email = models.EmailField(max_length=255, blank=True, null=True)
    profile_photo = models.ImageField(upload_to='profiles/', blank=True, null=True)

    def __str__(self): return self.user.username

class Category(models.Model):
    name = models.CharField(max_length=100)
    def __str__(self): return self.name

class Book(models.Model):
    # Added 'Unavailable' status for Librarian manual control
    STATUS_CHOICES = (('Available', 'Available'), ('Pending', 'Pending'), ('Borrowed', 'Borrowed'), ('Unavailable', 'Unavailable'))
    book_id = models.CharField(max_length=20, unique=True)
    title = models.CharField(max_length=255)
    author = models.CharField(max_length=255)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')

    def __str__(self): return f"[{self.book_id}] {self.title}"

class BorrowRecord(models.Model):
    book = models.ForeignKey(Book, on_delete=models.CASCADE)
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    borrow_date = models.DateField(auto_now_add=True)
    due_date = models.DateField()
    is_returned = models.BooleanField(default=False)
    return_date = models.DateField(null=True, blank=True)
    
    # NEW: Saves the final penalty to history permanently
    final_penalty = models.IntegerField(default=0)

    @property
    def penalty_fee(self):
        if self.is_returned: return self.final_penalty
        if self.book.status == 'Pending': return 0
        days_late = (date.today() - self.due_date).days
        return max(0, days_late * 5)

class Computer(models.Model):
    STATUS_CHOICES = (('Available', 'Available'), ('Requested', 'Requested'), ('In Use', 'In Use'))
    name = models.CharField(max_length=50)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')
    current_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    time_started = models.DateTimeField(null=True, blank=True)

class MeetingRoomSchedule(models.Model):
    STATUS_CHOICES = (('Upcoming', 'Upcoming'), ('Completed', 'Completed'))
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    date = models.DateField()
    time_slot = models.CharField(max_length=100)
    purpose = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Upcoming')