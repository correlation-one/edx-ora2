"""
Serializers for ORA's BFF.

These are the response shapes that power the MFE implementation of the ORA UI.
"""
# pylint: disable=abstract-method

from rest_framework.serializers import (
    BooleanField,
    IntegerField,
    Serializer,
    SerializerMethodField,
)

from openassessment.xblock.ui_mixins.mfe.assessment_serializers import (
    AssessmentResponseSerializer,
)
from openassessment.xblock.ui_mixins.mfe.submission_serializers import SubmissionSerializer

from .ora_config_serializer import RubricConfigSerializer


class AssessmentScoreSerializer(Serializer):
    """
    Returns:
    {
        earned: (Int) How many points were you awarded by peers?
        possible: (Int) What was the max possible grade?
    }
    """

    earned = IntegerField(source="points_earned", required=False)
    possible = IntegerField(source="points_possible", required=False)


class ReceivedGradesSerializer(Serializer):
    """
    Received grades for each of the applicable graded steps
    Returns:
    {
        self: (Assessment score object)
        peer: (Assessment score object)
        staff: (Assessment score object)
    }
    """

    self = AssessmentScoreSerializer(source="grades.self_score")
    peer = AssessmentScoreSerializer(source="grades.peer_score")
    staff = AssessmentScoreSerializer(source="grades.staff_score")

    def to_representation(self, instance):
        """
        Hook output to remove steps that are not part of the assignment.

        Grades are not released for steps until all steps are completed.
        """
        step_names = ["self", "peer", "staff"]

        # NOTE - cache this so we don't update the workflow
        configured_steps = instance.status_details.keys()
        is_done = instance.is_done

        for step in step_names:
            if step not in configured_steps:
                self.fields.pop(step)

        if not is_done:
            return {field: {} for field in self.fields}

        return super().to_representation(instance)


class TrainingStepInfoSerializer(Serializer):
    """
    Returns:
        {
            numberOfAssessmentsCompleted: (Int), progress through required assessments
            expectedRubricSelections: (List of rubric names and selections)
        }
    """

    numberOfAssessmentsCompleted = IntegerField(source="num_completed")
    expectedRubricSelections = SerializerMethodField()

    def get_expectedRubricSelections(self, instance):
        """
        Get expected rubric selections for Student Training step

        WARN: It is critical we do not hit this if we are not on the student
              training step, as loading an example will create a workflow.

        Returns: List of criterion names and matched selections
        [
            {
                name: (String) Criterion name,
                selection: (String) Option name that should be selected,
            }
        ]
        """
        example = instance.example

        options_selected = []
        for criterion in example["options_selected"]:
            criterion_selection = {
                "name": criterion,
                "selection": example["options_selected"][criterion],
            }
            options_selected.append(criterion_selection)

        return options_selected


class PeerStepInfoSerializer(Serializer):
    """
    Returns:
        {
            numberOfAssessmentsCompleted: (Int) Progress through required assessments
            isWaitingForSubmissions: (Bool) We've run out of peers to grade, waiting for more submissions
            numberOfReceivedAssessments: (Int) How many assessments has this response received
        }
    """

    numberOfAssessmentsCompleted = IntegerField(source="num_completed")
    isWaitingForSubmissions = BooleanField(source="waiting_for_submissions_to_assess")
    numberOfReceivedAssessments = IntegerField(source="num_received")


class ActiveStepInfoSerializer(Serializer):
    """
    Required context:
    * step - The active workflow step

    Returns:
    * Peer or learner training-specific data if on those steps
    * Empty dict for remaining steps
    """

    require_context = True

    def to_representation(self, instance):
        """
        Hook output to remove fields that are not part of the active step.
        """
        active_step = self.context["step"]

        if active_step == "training":
            return TrainingStepInfoSerializer(instance.student_training_data).data
        elif active_step == "peer":
            return PeerStepInfoSerializer(instance.peer_assessment_data()).data
        elif active_step in ("submission", "done"):
            return {}
        else:
            # pylint: disable=broad-exception-raised
            raise Exception(f"Bad step name: {active_step}")


class ProgressSerializer(Serializer):
    """
    Data about the progress of a user through their ORA workflow.

    Args: WorkflowAPI

    Returns:
    {
        // What step are we on? An index to the configuration from ORA config call.
        activeStepName: (String) one of ["training", "peer", "self", "staff"]

        hasReceivedFinalGrade: (Bool) // In effect, is the ORA complete?
        receivedGrades: (Object) Staff grade data, when there is a completed staff grade.
        activeStepInfo: (Object) Specific info for the active step
    }
    """

    activeStepName = SerializerMethodField()
    hasReceivedFinalGrade = BooleanField(source="workflow_data.is_done")
    receivedGrades = ReceivedGradesSerializer(source="workflow_data")
    activeStepInfo = ActiveStepInfoSerializer(source="*")

    def get_activeStepName(self, instance):
        """Return the active step name: one of 'submission"""
        if not instance.workflow_data.has_workflow:
            return "submission"
        else:
            return instance.workflow_data.status


class PageDataSerializer(Serializer):
    """
    Data for rendering a page in the ORA MFE

    Requires context to differentiate between Assessment and Submission views
    """

    require_context = True

    progress = ProgressSerializer(source="*")
    submission = SerializerMethodField()
    rubric = RubricConfigSerializer(source="*")

    def to_representation(self, instance):
        # Loading workflow status causes a workflow refresh
        # ... limit this to one refresh per page call
        active_step = instance.workflow_data.status or "submission"

        self.context.update({"step": active_step})
        return super().to_representation(instance)

    def get_submission(self, instance):
        """
        Has the following different use-cases:
        1) In the "submission" view, we get the user's draft / complete submission.
        2) In the "assessment" view, we get an assessment for the current assessment step.
        """

        if self.context.get("view") == "submission":
            return SubmissionSerializer(instance.submission_data).data
        elif self.context.get("view") == "assessment":
            return AssessmentResponseSerializer(instance.api_data, context=self.context).data
        else:
            # pylint: disable=broad-exception-raised
            raise Exception("Missing view context for page")